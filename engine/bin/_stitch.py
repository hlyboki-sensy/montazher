"""Склейка кількох фрагментів в один ролик — і карта часу до нього.

Порядок операцій узятий із дослідження `knowledge/self/montazher-research/
МЕТОДОЛОГІЯ.md`: спершу один файл, потім усе інше. Причина одна — Whisper має
дати час слів одразу у фінальному таймлайні. Якби ми транскрибували фрагменти
окремо, слово в зоні переходу жило б у двох фрагментах водночас, і правильного
відображення просто не існувало б.

Дві стадії:

  A. нормалізація кожного фрагмента окремо в work/pNN.mp4 — однакові розмір,
     частота кадрів, колір, звук, взаємна гучність;
  B. склейка вже однакових частин — стик через concat demuxer, зсув через
     xfade/acrossfade.

Чому не один великий filter_complex із нормалізацією всередині: фільтри в
кожного фрагмента свої (один HLG, другий SDR, третій горизонтальний), граф стає
нечитабельним, а карта часу мусить будуватися з ВИМІРЯНИХ довжин, а не планових.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Кадр вертикального ролика й частота, до якої зводимо все.
FRAME_W, FRAME_H = 1080, 1920
FPS = 30

# Мікрофейд у краї кожного фрагмента прибирає клац на стику. Більше за 0,03 с
# не беремо — зʼїдає атаку першого слова.
EDGE_FADE = 0.02

# Типове мʼяке затемнення. Живе ВСЕРЕДИНІ власної довжини фрагмента, тож
# тривалість лишається строго аддитивною і субтитрам нема куди поїхати.
BLACK_FADE = 0.16

# Взаємне вирівнювання фрагментів перед склейкою — не більше ніж на стільки.
MAX_PREGAIN_DB = 6.0


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"{what} впало:\n{res.stderr[-1500:]}")
    return res


def probe(path: Path) -> dict:
    """Паспорт фрагмента: розмір, поворот, частота, тривалість, колір, звук.

    Поворот читаємо з `side_data_list` — телефон пише горизонтальний кадр плюс
    матрицю повороту, і без цього другий фрагмент грає боком. Окремо важливо,
    що concat demuxer бере метадані з ПЕРШОГО файлу, тож поворот мусить бути
    вже запечений у пікселі на стадії A.
    """
    res = _run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        "Читання паспорта",
    )
    data = json.loads(res.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        sys.exit(f"У {path.name} немає відеодоріжки")

    rotation = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    if not rotation:
        rotation = int((v.get("tags") or {}).get("rotate", 0) or 0)

    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = (float(num) / float(den)) if float(den or 0) else 0.0

    return {
        "path": path,
        "width": int(v["width"]),
        "height": int(v["height"]),
        "rotation": ((rotation % 360) + 360) % 360,
        "fps": fps,
        "duration": float(data["format"].get("duration") or 0.0),
        "transfer": v.get("color_transfer", ""),
        "primaries": v.get("color_primaries", ""),
        "sar": v.get("sample_aspect_ratio", "1:1"),
        "has_audio": a is not None,
    }


def loudness(path: Path) -> float | None:
    """Інтегрована гучність фрагмента в LUFS. None — якщо виміряти не вийшло."""
    res = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    start = res.stderr.rfind("{")
    end = res.stderr.find("}", start)
    if start < 0 or end < 0:
        return None
    try:
        return float(json.loads(res.stderr[start:end + 1])["input_i"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _video_chain(p: dict, fade_in: float, fade_out: float, dur: float) -> str:
    """Ланцюжок фільтрів для одного фрагмента — до спільного знаменника."""
    chain = []

    # Поворот запікаємо в пікселі: далі про матрицю ніхто не згадає.
    if p["rotation"] == 90:
        chain.append("transpose=1")
    elif p["rotation"] == 270:
        chain.append("transpose=2")
    elif p["rotation"] == 180:
        chain.append("transpose=1,transpose=1")

    # HDR (HLG/PQ) без тон-мапінгу вигорає: шкіра стає паперовою.
    if p["transfer"] in ("arib-std-b67", "smpte2084"):
        chain += [
            "zscale=t=linear:npl=100",
            "tonemap=hable:desat=0",
            "zscale=p=bt709:t=bt709:m=bt709:r=tv",
        ]

    chain += [
        f"scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=decrease",
        f"pad={FRAME_W}:{FRAME_H}:(ow-iw)/2:(oh-ih)/2:color=black",
        # setsar ОБОВʼЯЗКОВО після scale/pad — інакше фрагмент їде розтягнутим.
        "setsar=1",
        f"fps={FPS}",
        "format=yuv420p",
    ]

    # Затемнення всередині власної довжини: хвіст гасне, голова наступного
    # виходить із чорного, а стик лишається звичайним.
    if fade_in > 0:
        chain.append(f"fade=t=in:st=0:d={fade_in:g}")
    if fade_out > 0 and dur > fade_out:
        chain.append(f"fade=t=out:st={dur - fade_out:.3f}:d={fade_out:g}")

    return ",".join(chain)


def _audio_chain(gain_db: float, fade_out_at: float) -> str:
    chain = [
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
        # first_pts=0 прибиває AAC priming: без нього звук повзе на 20-45 мс за шов.
        "aresample=48000:first_pts=0",
        # Тло в кожного фрагмента своє; зріз низів робить шви непомітнішими.
        "highpass=f=70",
    ]
    if abs(gain_db) > 0.1:
        chain.append(f"volume={gain_db:.2f}dB")
    chain.append(f"afade=t=in:st=0:d={EDGE_FADE:g}")
    if fade_out_at > EDGE_FADE:
        chain.append(f"afade=t=out:st={fade_out_at:.3f}:d={EDGE_FADE:g}")
    return ",".join(chain)


def normalize(p: dict, out: Path, gain_db: float, fade_in: float, fade_out: float) -> Path:
    """Стадія A: один фрагмент → спільний знаменник."""
    dur = p["duration"]
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        # Дірки в таймстемпах і edit lists із телефона ламають -ss далі по колії.
        "-fflags", "+genpts",
        "-i", str(p["path"]),
        "-vf", _video_chain(p, fade_in, fade_out, dur),
    ]
    if p["has_audio"]:
        cmd += ["-af", _audio_chain(gain_db, max(dur - EDGE_FADE, 0.0)),
                "-map", "0:v:0", "-map", "0:a:0"]
    else:
        # Без звуку фрагмент не склеїться з іншими — підставляємо тишу.
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += [
        "-r", str(FPS), "-fps_mode", "cfr",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-video_track_timescale", "30000",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(out),
    ]
    _run(cmd, f"Нормалізація {p['path'].name}")
    return out


def _concat(parts: list[Path], out: Path, work: Path) -> Path:
    """Стадія B, стик: частини вже однакові, тож відео копіюємо як є.

    Звук свідомо перекодовуємо (`-c:a aac`, ніколи `copy`) — саме тут
    убивається AAC priming, інакше кожен шов несе по ~21 мс зайвого.
    """
    lst = work / "concat.txt"
    lst.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8"
    )
    _run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
          "-i", str(lst), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-movflags", "+faststart", str(out)], "Склейка")
    return out


def _xfade(parts: list[Path], out: Path, overlap: float, durs: list[float]) -> Path:
    """Стадія B, зсув: фрагменти наїжджають один на одного на `overlap` секунд."""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]

    steps, vprev, aprev, acc = [], "0:v", "0:a", durs[0]
    for i in range(1, len(parts)):
        vout, aout = f"v{i}", f"a{i}"
        offset = acc - overlap
        steps.append(
            f"[{vprev}][{i}:v]xfade=transition=fade:duration={overlap:g}:"
            f"offset={offset:.3f}[{vout}]"
        )
        steps.append(f"[{aprev}][{i}:a]acrossfade=d={overlap:g}[{aout}]")
        vprev, aprev = vout, aout
        acc = offset + durs[i]

    cmd += [
        "-filter_complex", ";".join(steps),
        "-map", f"[{vprev}]", "-map", f"[{aprev}]",
        "-r", str(FPS), "-fps_mode", "cfr",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(out),
    ]
    _run(cmd, "Склейка зі зсувом")
    return out


def plan_hash(paths: list[Path], fade: float, overlap: float) -> str:
    """Детермінована назва збірки — щоб повторний запуск не зшивав удруге."""
    key = "|".join(f"{p.resolve()}:{p.stat().st_size}" for p in paths)
    key += f"|fade={fade:g}|overlap={overlap:g}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def stitch(paths: list[Path], work: Path, fade: float = BLACK_FADE,
           overlap: float = 0.0) -> tuple[Path, list[dict]]:
    """Зшиває фрагменти в один ролик. Повертає готовий файл і карту часу.

    `fade` — мʼяке затемнення на стику (0 — встик).
    `overlap` — зсув: фрагменти наїжджають один на одного. Разом із `fade` не
    вживається: зсув сам по собі і є переходом.
    """
    work.mkdir(parents=True, exist_ok=True)
    tag = plan_hash(paths, fade, overlap)
    final = work / f"reel-{tag}.mp4"
    map_file = work / f".reel-{tag}.stitch.json"

    if final.exists() and map_file.exists():
        print(f"  беру готову склейку: {final.name}")
        return final, json.loads(map_file.read_text(encoding="utf-8"))

    if overlap > 0:
        fade = 0.0

    print(f"→ Зшиваю {len(paths)} фрагменти…")
    passports = [probe(p) for p in paths]

    # Взаємне вирівнювання рівня рахуємо від МЕДІАНИ, не від середнього: один
    # тихий фрагмент не має тягнути за собою решту. Абсолютну гучність доводимо
    # одним loudnorm уже після склейки — по фрагментах не можна, бо він стискає
    # динаміку по-різному і тло починає «дихати» на швах.
    levels = [loudness(p) for p in paths]
    known = sorted(x for x in levels if x is not None)
    median = known[len(known) // 2] if known else None
    gains = [
        0.0 if (median is None or lv is None)
        else max(-MAX_PREGAIN_DB, min(MAX_PREGAIN_DB, median - lv))
        for lv in levels
    ]

    parts, durs = [], []
    for i, (p, g) in enumerate(zip(passports, gains)):
        dst = work / f"p{i:02d}.mp4"
        fi = fade if (fade > 0 and i > 0) else 0.0
        fo = fade if (fade > 0 and i < len(passports) - 1) else 0.0
        print(f"  {i + 1}/{len(passports)} {p['path'].name} "
              f"({p['width']}×{p['height']}"
              + (f", поворот {p['rotation']}°" if p["rotation"] else "")
              + (", HDR" if p["transfer"] in ("arib-std-b67", "smpte2084") else "")
              + (f", рівень {g:+.1f} дБ" if abs(g) > 0.1 else "") + ")")
        normalize(p, dst, g, fi, fo)
        # Довжину беремо ВИМІРЯНУ з готової частини, не планову з оригіналу:
        # саме на цій різниці карта часу й починала брехати.
        durs.append(probe(dst)["duration"])
        parts.append(dst)

    if overlap > 0:
        _xfade(parts, final, overlap, durs)
    else:
        _concat(parts, final, work)

    # Карта часу: який відрізок готового ролика звідки походить.
    time_map, at = [], 0.0
    for i, (p, d) in enumerate(zip(passports, durs)):
        time_map.append({
            "index": i,
            "src": p["path"].name,
            "atSec": round(at, 3),
            "durSec": round(d, 3),
            "seamAt": None if i == 0 else round(at, 3),
        })
        at += d - (overlap if i < len(durs) - 1 else 0.0)

    map_file.write_text(json.dumps(time_map, ensure_ascii=False, indent=1), encoding="utf-8")
    total = probe(final)["duration"]
    print(f"  ✓ {final.name} — {total:.1f} с із {len(parts)} фрагментів")
    return final, time_map


def seams(time_map: list[dict]) -> list[float]:
    """Моменти швів у готовому ролику."""
    return [m["seamAt"] for m in time_map if m["seamAt"] is not None]


def guard_seams(spans: list[tuple[float, float]], time_map: list[dict],
                fade: float, overlap: float) -> list[tuple[float, float]]:
    """Прибирає різи, що влучили в шов.

    `--cut-pauses` майже завжди знаходить провал саме на стику — він там за
    побудовою — і може відрізати частину затемнення або середину переходу.
    """
    if not spans:
        return spans
    pad = max(overlap, fade) + 0.10
    kept = []
    for a, b in spans:
        if any(a < s + pad and b > s - pad for s in seams(time_map)):
            continue
        kept.append((a, b))
    return kept
