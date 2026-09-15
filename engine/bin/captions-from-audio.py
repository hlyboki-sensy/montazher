#!/usr/bin/env python3
"""Транскрипція аудіо/відео → готові props для Remotion-композицій пакета.

Серце монтажера. Розпізнає мову локально (faster-whisper, без ключів і без
мережі), дістає час КОЖНОГО слова й складає з них репліки: де вони стоять у
кадрі, як довго живуть, яким стилем написані, чи не сідають на обличчя та на
інтерфейс майданчика.

Приклад:
    python3 engine/bin/captions-from-audio.py inbox/reel.mp4 --mode reel
    python3 engine/bin/captions-from-audio.py voice.mp3 --model small   # чернетка, швидше

Далі: npx remotion studio → композиція KineticReel/KineticCaptions,
props підставляються з engine/src/data/<імʼя>.captions.json.

Автор: Олена Дубицька — @hlyboki_sensy · hlyboki-sensy.com
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _faces  # noqa: E402
import _paths  # noqa: E402
import _library  # noqa: E402
import _cuts  # noqa: E402
import _luma  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA_DIR = PROJECT / "src" / "data"

# Розпізнавання мови — локальне, через faster-whisper. Нічого не йде в мережу
# (крім першого разу, коли модель сама завантажується), ключі не потрібні.

# Порожні службові слова: їх пишемо тонким рукописним стилем, щоб у кадрі
# «важчали» тільки змістовні слова.
FUNCTION_WORDS = {
    "і", "й", "та", "а", "але", "бо", "що", "як", "це", "цей", "ця", "те",
    "то", "у", "в", "з", "із", "зі", "на", "до", "за", "по", "від", "для",
    "про", "при", "над", "під", "без", "не", "ні", "ж", "би", "б", "же",
    "я", "ти", "ви", "ми", "він", "вона", "воно", "вони", "мене", "тебе",
    "вам", "нам", "їх", "його", "її", "мій", "моя", "ваш", "наш", "так",
    "ось", "от", "ну", "вже", "ще", "тут", "там", "коли", "чи", "або",
}

# Якорі для реплік у безпечній зоні 9:16. Правий нижній кут пропущено —
# там кнопки лайк/коментар/поділитись.
ANCHORS = [
    (0.07, 0.27, "left"),
    (0.93, 0.33, "right"),
    (0.50, 0.42, "center"),
    (0.07, 0.50, "left"),
    (0.50, 0.30, "center"),
    (0.93, 0.24, "right"),
    (0.50, 0.52, "center"),
    (0.07, 0.38, "left"),
]


def transcribe(path: Path, model: str, language: str) -> list[dict]:
    """Повертає список слів [{word, start, end, probability}].

    Результат кешується поруч із відео: перебирати стилі на одному ролику —
    звична справа, а розпізнавання щоразу заново коштує хвилини на порожньому
    місці. Кеш протухає, якщо відео змінилося або взято іншу модель чи мову.
    """
    cache = path.parent / f".{path.stem}.words.json"
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("model") == model and saved.get("language") == language:
                print(f"  беру готову розшифровку: {cache.name}")
                return saved["words"]
        except (json.JSONDecodeError, KeyError):
            pass  # зіпсований кеш — просто розпізнаємо заново

    python = _paths.python_with("faster_whisper")
    code = (
        "import sys, json\n"
        "from faster_whisper import WhisperModel\n"
        "model = WhisperModel(%r, device='cpu', compute_type='int8')\n"
        "segments, info = model.transcribe(%r, language=%r, word_timestamps=True, vad_filter=True)\n"
        "words = []\n"
        "for seg in segments:\n"
        "    for w in (seg.words or []):\n"
        "        words.append({'word': w.word, 'start': w.start, 'end': w.end,\n"
        "                      'probability': getattr(w, 'probability', None)})\n"
        "sys.stdout.write('@@JSON@@' + json.dumps({'ok': True, 'err': None, 'words': words},\n"
        "                 ensure_ascii=False))\n"
        % (model, str(path), language)
    )
    proc = subprocess.run([python, "-c", code], capture_output=True, text=True)
    if "@@JSON@@" not in proc.stdout:
        sys.exit(
            "Транскрипція впала.\n"
            "Найчастіша причина — не встановлено faster-whisper: запусти ./install.sh\n\n"
            + proc.stderr[-2000:]
        )
    payload = json.loads(proc.stdout.split("@@JSON@@", 1)[1])
    if not payload["ok"]:
        sys.exit(f"Транскрипція впала: {payload['err']}")
    words = payload["words"]
    cache.write_text(
        json.dumps({"model": model, "language": language, "words": words}, ensure_ascii=False),
        encoding="utf-8",
    )
    return words


def merge_fragments(words: list[dict]) -> list[dict]:
    """Склеює те, що Whisper розриває пробілом: «111 -денного», «ім \'я», «по -іншому».

    Модель віддає дефіс і апостроф окремими токенами з провідним пробілом, тож
    без цього кроку в кадр летять уламки слів.
    """
    out: list[dict] = []
    for w in words:
        text = w["word"]
        bare = text.strip()
        if not bare:
            continue
        glue_back = out and (bare[0] in "-\u2019'" or out[-1]["word"].rstrip().endswith(("-", "\u2019", "'")))
        if glue_back:
            prev = out[-1]
            prev["word"] = prev["word"].rstrip() + bare
            prev["end"] = w["end"]
            prev["probability"] = min(
                prev.get("probability", 1.0), w.get("probability", 1.0)
            )
            continue
        out.append(dict(w))
    return out


def clean(raw: str) -> str:
    return raw.strip()


def style_for(word: str, is_accent: bool) -> str:
    if is_accent:
        return "accent"
    bare = word.strip(" ,.!?…:;—-«»\"'").lower()
    if bare in FUNCTION_WORDS or len(bare) <= 2:
        return "script"
    return "bold"


def salience(word: str) -> int:
    """Наскільки слово «важке» — довші змістовні слова тягнуть акцент на себе."""
    bare = word.strip(" ,.!?…:;—-«»\"'").lower()
    if bare in FUNCTION_WORDS:
        return 0
    return len(bare)


def group_into_cues(
    words: list[dict], max_words: int, gap: float, max_dur: float
) -> list[list[dict]]:
    """Ріже потік слів на репліки за паузами, довжиною і кількістю слів."""
    cues: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        if not clean(w["word"]):
            continue
        if current:
            pause = w["start"] - current[-1]["end"]
            too_long = w["end"] - current[0]["start"] > max_dur
            ends_sentence = current[-1]["word"].strip().endswith((".", "!", "?", "…"))
            if pause > gap or too_long or len(current) >= max_words or ends_sentence:
                cues.append(current)
                current = []
        current.append(w)
    if current:
        cues.append(current)
    return cues


def cue_to_lines(cue: list[dict]) -> list[dict]:
    """Розкладає репліку на 1–2 рядки й розставляє стилі."""
    accent_idx = max(range(len(cue)), key=lambda i: salience(cue[i]["word"]))
    if salience(cue[accent_idx]["word"]) < 4:
        accent_idx = -1  # немає достатньо «важкого» слова — обходимось без акценту

    tokens = [
        {"text": clean(w["word"]), "style": style_for(w["word"], i == accent_idx)}
        for i, w in enumerate(cue)
    ]
    if len(tokens) <= 3:
        return [{"words": tokens}]
    half = (len(tokens) + 1) // 2
    return [{"words": tokens[:half]}, {"words": tokens[half:]}]


def source_fps(path: Path) -> float:
    """Частота кадрів вихідного файлу."""
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate", "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True,
    )
    lines = (res.stdout or "").strip().splitlines()
    raw = lines[0] if lines else "30/1"
    try:
        num, den = raw.split("/")
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        value = 30.0
    return round(value) if value > 1 else 30.0


def speed_up(source: Path, factor: float, out_dir: Path) -> Path:
    """Пришвидшує відео, не змінюючи висоту голосу.

    atempo розтягує час методом WSOLA: він ріже звук на короткі вікна і склеює
    їх щільніше, тому мова стає швидшою, а тембр лишається твоїм. Це не те саме,
    що просто крутити файл швидше — там голос поповз би вгору.
    """
    out = out_dir / f"{source.stem}-x{factor:g}.mp4"
    fps = source_fps(source)
    print(f"→ Пришвидшую в {factor:g}× (голос не змінюється, {fps:g} кадр/с)…")
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", str(source),
        "-filter_complex",
        f"[0:v]setpts=PTS/{factor}[v];[0:a]atempo={factor}[a]",
        "-map", "[v]", "-map", "[a]",
        # Без явного -r ffmpeg скидає вихід до 25 кадр/с і викидає більшість
        # кадрів — рух стає рваним. Тримаємо частоту вихідного файлу.
        "-r", f"{fps:g}", "-fps_mode", "cfr",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"Пришвидшення впало:\n{res.stderr[-1500:]}")
    print(f"  ✓ {out.name}")
    return out


# Гучність, до якої Instagram і TikTok підтягують усі ролики.
TARGET_LUFS = -14


def polish(source: Path, out_dir: Path, audio: bool, color: bool) -> Path:
    """Вирівнює гучність і/або підправляє колір, не чіпаючи геометрію кадру.

    Гучність: `loudnorm` веде запис до -14 LUFS — це та гучність, до якої
    Instagram і TikTok однаково підтягують усі ролики. Коли зводиш сама, ролик
    у стрічці звучить або тихішим, або перетиснутим; тут він звучить як сусідні.

    Колір: делікатний `eq` плюс легка різкість. Свідомо мало: знімок із телефона
    вже оброблений, і сильна корекція робить із живого кадру пластик.

    Кадри не зсуваються й не змінюють розмір, тож таймінги реплік і знайдені
    рамки облич лишаються чинними.
    """
    tag = ("-a" if audio else "") + ("-c" if color else "")
    out = out_dir / f"{source.stem}{tag}.mp4"
    fps = source_fps(source)
    what = " і ".join(x for x in (["гучність"] if audio else []) + (["колір"] if color else []))
    print(f"→ Вирівнюю {what}…")

    # loudnorm за один прохід промахується на пару децибел: він не знає наперед,
    # наскільки гучний запис загалом. Тому спершу міряємо, потім вирівнюємо з
    # готовими числами — так ролик сідає рівно на цільову гучність.
    measured = None
    if audio:
        # Саме -v info: на рівні error ffmpeg не друкує звіт вимірювання взагалі.
        probe = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(source), "-af",
             f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True,
        )
        start = probe.stderr.rfind("{")
        end = probe.stderr.find("}", start)
        try:
            measured = json.loads(probe.stderr[start:end + 1]) if start >= 0 else None
        except json.JSONDecodeError:
            measured = None   # не виміряли — лишаємось на одному проході
        if measured:
            print(f"  було {measured['input_i']} LUFS, ціль {TARGET_LUFS}")

    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(source)]
    if color:
        cmd += ["-vf", "eq=contrast=1.07:saturation=1.10:gamma=1.02,unsharp=5:5:0.4:5:5:0.0"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
                "-r", f"{fps:g}", "-fps_mode", "cfr"]
    else:
        cmd += ["-c:v", "copy"]
    if audio:
        norm = f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11"
        if measured:
            # ПАСТКА: самих measured_* мало. Перший прохід окремо звітує
            # target_offset — наскільки він промахнеться повз ціль; без явного
            # offset ролик стабільно виходить на ці два децибели тихішим.
            norm += (
                f":measured_I={measured['input_i']}"
                f":measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}"
                f":measured_thresh={measured['input_thresh']}"
                f":offset={measured.get('target_offset', 0)}"
                ":linear=true"
            )
        cmd += ["-af", norm, "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "copy"]
    cmd.append(str(out))

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"Обробка впала:\n{res.stderr[-1500:]}")
    print(f"  ✓ {out.name}")
    return out


# --- Розкладка реплік у кадрі -------------------------------------------------
# Кадр 1080×1920. Безпечне поле — з відступами від країв, щоб нічого не влипало
# в межу. Правий нижній кут віддано кнопкам Instagram (лайк/коментар/поділитись).
FRAME_W, FRAME_H = 1080, 1920
SAFE_L, SAFE_R, SAFE_T, SAFE_B = 0.06, 0.94, 0.16, 0.80
UI_X, UI_Y = 0.82, 0.55

# Сліпі зони майданчиків — прямокутники в частках кадру 9:16, де інтерфейс
# самої платформи лежить ПОВЕРХ відео: колонка лайків, підпис, музика, таймлайн
# сторіс. Текст, який туди потрапив, глядач просто не побачить, тож для
# розкладки вони така сама перешкода, як обличчя чи вставка.
#
# Числа зняті з реальних скріншотів і взяті з запасом: краще трохи більше
# вільного поля, ніж репліка під кнопкою «поділитися».
PLATFORM_ZONES = {
    "reels": [
        {"x": 0.00, "y": 0.00, "w": 1.00, "h": 0.10},   # статус-бар і напис Reels
        {"x": 0.80, "y": 0.40, "w": 0.20, "h": 0.52},   # колонка іконок праворуч
        {"x": 0.00, "y": 0.78, "w": 0.82, "h": 0.22},   # імʼя, підпис, музика
    ],
    "tiktok": [
        {"x": 0.00, "y": 0.00, "w": 1.00, "h": 0.10},
        {"x": 0.79, "y": 0.38, "w": 0.21, "h": 0.52},
        {"x": 0.00, "y": 0.76, "w": 0.80, "h": 0.24},
    ],
    "shorts": [
        {"x": 0.00, "y": 0.00, "w": 1.00, "h": 0.09},
        {"x": 0.82, "y": 0.40, "w": 0.18, "h": 0.50},
        {"x": 0.00, "y": 0.80, "w": 0.84, "h": 0.20},
    ],
    "stories": [
        {"x": 0.00, "y": 0.00, "w": 1.00, "h": 0.13},   # смужки часу й аватар
        {"x": 0.00, "y": 0.86, "w": 1.00, "h": 0.14},   # «Надіслати повідомлення»
    ],
    "linkedin": [
        {"x": 0.00, "y": 0.00, "w": 1.00, "h": 0.08},
        {"x": 0.00, "y": 0.84, "w": 1.00, "h": 0.16},
    ],
}


def platform_zones(dest: str) -> list[dict]:
    """Сліпі зони обраного майданчика; невідома назва — без зон."""
    return [dict(z) for z in PLATFORM_ZONES.get((dest or "").strip().lower(), [])]

# Метрики шрифтів із композиції — свої на кожен характер субтитрів.
#   (кегль, СЕРЕДНЯ ширина літери, НАЙШИРША ширина літери, висота рядка)
#
# Ширини не на око: заміряні в браузері тими самими шрифтами й накресленнями,
# що йдуть у рендер, на українському тексті (з урахуванням letter-spacing і
# uppercase). Раніше тут стояли приблизні числа з приміткою «точність не
# критична» — і це була помилка: рукописним родинам ширину недооцінювали на
# 40-55%, тож блок «нібито влазив», а в кадрі вилітав за межі. Найгірше в
# podcast-hero і calligraphy, де рукопис найбільший.
#
# Два коефіцієнти потрібні різним перевіркам:
#   середній — для загальної ширини рядка (на кількох словах похибка гасне);
#   найширший — для перевірки «чи влізе найдовше СЛОВО», бо саме окреме слово
#   переносу не має й вилазить за смугу цілком.
LOOK_METRICS = {
    # щіточний рукопис Comforter Brush + важкий капс Montserrat
    "editorial": {"script": (104, 0.59, 0.83, 122), "sans": (62, 0.75, 0.89, 62),
                  "gap": 22, "overlap": 14},
    # тихе біле Inter малими літерами — одного розміру для всіх ролей
    "quiet": {"script": (56, 0.62, 0.87, 64), "sans": (56, 0.62, 0.87, 64),
              "gap": 14, "overlap": -4},
    # білий капс Montserrat із кольоровим ключовим словом
    "bold": {"script": (64, 0.75, 0.89, 66), "sans": (64, 0.75, 0.89, 66),
             "gap": 18, "overlap": 6},
    # дідонівський серіф: курсив + капс з однієї родини
    "classic": {"script": (104, 0.61, 0.84, 118), "sans": (68, 0.78, 0.92, 70),
                "gap": 20, "overlap": 10},
    # велика каліграфія Great Vibes + важкий капс
    "calligraphy": {"script": (132, 0.60, 0.84, 150), "sans": (72, 0.75, 0.89, 74),
                    "gap": 24, "overlap": 18},
    # дрібне біле для потоку; ключові репліки беруть метрики "hero"
    "podcast": {
        "script": (56, 0.62, 0.87, 64), "sans": (56, 0.62, 0.87, 64),
        "gap": 14, "overlap": -4,
        "hero": {"script": (176, 0.60, 0.84, 198), "sans": (128, 0.75, 0.89, 130),
                 "gap": 26, "overlap": 26},
    },
}
LOOKS = tuple(LOOK_METRICS)
_look = "editorial"


def set_look(name: str) -> None:
    """Перемикає метрики розкладки під обраний характер субтитрів."""
    global _look
    _look = name if name in LOOK_METRICS else "editorial"


_hero = False


def set_hero(on: bool) -> None:
    """Вмикає метрики другого поверху — для ключових, великих реплік."""
    global _hero
    _hero = on


def metrics() -> dict:
    m = LOOK_METRICS[_look]
    return m["hero"] if _hero and "hero" in m else m
MIN_BAND_H = 0.06
# Повітря між рамкою обличчя і текстом: щоб репліка не тулилася впритул.
FACE_GAP = 0.03
# Найменший шматок смуги, який ще має сенс лишати після вирізання вставки.
# Свідомо менший за MIN_BAND_H: тісна репліка краща за репліку поверх вставки.
SPLIT_FLOOR = 0.045


def _face(word: dict) -> tuple:
    m = metrics()
    return m["script"] if word["style"] == "script" else m["sans"]


def word_width(word: dict) -> float:
    """Очікувана ширина слова — за середньою шириною літери."""
    size, adv, _, _ = _face(word)
    return len(word["text"]) * size * adv


def word_width_max(word: dict) -> float:
    """Ширина слова в найгіршому випадку — усі літери широкі.

    Саме це число вирішує, чи слово влізе у смугу: окреме слово переносу не має,
    тож недооцінка тут означає напис, що вилітає за кадр.
    """
    size, _, adv_max, _ = _face(word)
    return len(word["text"]) * size * adv_max


def measure(lines: list[dict]) -> dict:
    """Груба оцінка розмірів текстового блока в пікселях."""
    rows = []
    for line in lines:
        ws = line["words"]
        m = metrics()
        width = sum(word_width(w) for w in ws) + m["gap"] * max(len(ws) - 1, 0)
        height = max((m["script"][3] if w["style"] == "script" else m["sans"][3]) for w in ws)
        longest = max(word_width_max(w) for w in ws)
        rows.append({"width": width, "height": height, "longest": longest})
    return {
        "rows": rows,
        "width": max(r["width"] for r in rows),
        "longest_word": max(r["longest"] for r in rows),
    }


def wrapped_height(block: dict, band_w_px: float, scale: float = 1.0) -> float:
    """Скільки заввишки стане блок, якщо його втиснути в задану ширину."""
    total = 0.0
    for r in block["rows"]:
        needed = max(1, math.ceil(r["width"] * scale / max(band_w_px, 1)))
        total += r["height"] * scale * needed
    return total - metrics()["overlap"] * scale * (len(block["rows"]) - 1)


# На скільки дозволено зменшити текст, аби він вліз у вільну смугу. Нижче цього
# великий напис перестає бути великим — тоді чесніше зробити його звичайним.
SCALE_STEPS = [1.0, 0.92, 0.84, 0.76, 0.68, 0.6, 0.52, 0.45]


# Менше цього напис уже не прочитати — але навіть такий дрібний напис у кадрі
# кращий за великий, що вилітає за край.
MIN_SCALE = 0.34


def clamp_scale(block: dict, band: dict, scale: float) -> float:
    """Доводить масштаб до того, за якого блок ГАРАНТОВАНО в межах смуги.

    `fit_scale` перебирає готові сходинки й може повернути None — тоді раніше
    бралася остання сходинка «на віру», і саме там напис вилітав за кадр.
    Тут ширина рахується напряму: скільки треба, стільки й буде.
    """
    w_px, h_px = band["w"] * FRAME_W, band["h"] * FRAME_H
    if block["longest_word"] > 0:
        # Найдовше слово переносу не має — воно й задає верхню межу масштабу.
        scale = min(scale, w_px / block["longest_word"])
    # Далі підганяємо висоту: кількість рядків залежить від масштабу, тож
    # зменшуємо кроками, аж поки блок не вміститься.
    for _ in range(14):
        if wrapped_height(block, w_px, scale) <= h_px or scale <= MIN_SCALE:
            break
        scale *= 0.94
    return round(max(min(scale, 1.0), MIN_SCALE), 3)


def fit_scale(block: dict, band: dict) -> float | None:
    """Найбільший масштаб, за якого блок ще вміщується у смугу. None — не влазить.

    Це і є захист від напису на обличчі: раніше блок, який нікуди не вліз,
    однаково ставили в найбільшу смугу, і він вилазив за її межі — просто на
    очі й губи. Тепер він або стискається до розміру смуги, або не великий.
    """
    w_px, h_px = band["w"] * FRAME_W, band["h"] * FRAME_H
    for s in SCALE_STEPS:
        if block["longest_word"] * s > w_px:
            continue
        if wrapped_height(block, w_px, s) > h_px:
            continue
        return s
    return None


def free_bands(face: dict | None) -> dict[str, dict]:
    """Вільні смуги навколо обличчя, у частках кадру."""
    bands: dict[str, dict] = {}
    if face is None:
        bands["bottom"] = {"x": SAFE_L, "w": UI_X - SAFE_L, "y": 0.58, "h": SAFE_B - 0.58}
        bands["top"] = {"x": SAFE_L, "w": SAFE_R - SAFE_L, "y": SAFE_T, "h": 0.34 - SAFE_T}
        return bands

    f_top = face["y"] - FACE_GAP
    f_bottom = face["y"] + face["h"] + FACE_GAP
    f_left = face["x"] - FACE_GAP
    f_right = face["x"] + face["w"] + FACE_GAP

    top_h = f_top - SAFE_T
    if top_h >= MIN_BAND_H:
        bands["top"] = {"x": SAFE_L, "w": SAFE_R - SAFE_L, "y": SAFE_T, "h": top_h}

    bottom_y = max(f_bottom, SAFE_T)
    bottom_h = SAFE_B - bottom_y
    if bottom_h >= MIN_BAND_H:
        right_edge = UI_X if SAFE_B > UI_Y else SAFE_R
        bands["bottom"] = {"x": SAFE_L, "w": right_edge - SAFE_L, "y": bottom_y, "h": bottom_h}

    left_w = f_left - SAFE_L
    if left_w >= 0.22:
        bands["left"] = {"x": SAFE_L, "w": left_w, "y": max(f_top, SAFE_T), "h": min(f_bottom, SAFE_B) - max(f_top, SAFE_T)}

    right_edge = UI_X if f_bottom > UI_Y else SAFE_R
    right_w = right_edge - f_right
    if right_w >= 0.22:
        bands["right"] = {"x": f_right, "w": right_w, "y": max(f_top, SAFE_T), "h": min(f_bottom, SAFE_B) - max(f_top, SAFE_T)}

    return bands


def split_band(band: dict, blocks: list[dict]) -> list[dict]:
    """Ріже смугу на вільні шматки там, де її перетинає перешкода.

    Перешкода заважає лише там, де справді накриває смугу. Вузька колонка
    іконок збоку не повинна з'їдати смугу по всій висоті — від неї достатньо
    відступити вбік; і навпаки, підпис знизу ріже смугу по висоті.
    """
    pieces = [band]
    for b in blocks:
        nxt = []
        for piece in pieces:
            top, bottom = piece["y"], piece["y"] + piece["h"]
            left, right = piece["x"], piece["x"] + piece["w"]
            b_top, b_bottom = b["y"] - FACE_GAP, b["y"] + b["h"] + FACE_GAP
            b_left, b_right = b["x"] - FACE_GAP, b["x"] + b["w"] + FACE_GAP

            # Не перетинаються по вертикалі або по горизонталі — не заважає.
            if b_bottom <= top or b_top >= bottom or b_right <= left or b_left >= right:
                nxt.append(piece)
                continue

            # Перешкода тулиться до краю смуги — звужуємо смугу вбік.
            if b_left <= left and b_right < right:
                nxt.append({**piece, "x": b_right, "w": right - b_right})
                continue
            if b_right >= right and b_left > left:
                nxt.append({**piece, "x": left, "w": b_left - left})
                continue

            # Накриває смугу на всю ширину — ріжемо по висоті.
            if b_top - top >= SPLIT_FLOOR:
                nxt.append({**piece, "y": top, "h": b_top - top})
            if bottom - b_bottom >= SPLIT_FLOOR:
                nxt.append({**piece, "y": b_bottom, "h": bottom - b_bottom})
        pieces = [pc for pc in nxt if pc["w"] > 0.12 and pc["h"] > 0.02]
    return pieces


# Скільки реплік поспіль лишаються на одному місці у «тихому» ритмі.
QUIET_GROUP = 4


# Дотик межі — не перетин. Допуск у дві тисячні кадру (≈2 пікселі на 1080)
# гасить порохню з округлення часток: без нього репліка, що закінчується рівно
# там, де починається обличчя, вважалася написом на лиці.
OVERLAP_EPS = 0.002


def boxes_overlap(a: dict, b: dict) -> bool:
    """Чи перетинаються дві зони — тобто чи можна лишити репліку на місці."""
    return (
        a["x"] + OVERLAP_EPS < b["x"] + b["w"] and b["x"] + OVERLAP_EPS < a["x"] + a["w"]
        and a["y"] + OVERLAP_EPS < b["y"] + b["h"] and b["y"] + OVERLAP_EPS < a["y"] + a["h"]
    )


def active_at(items: list[dict], start: float, end: float) -> list[dict]:
    """Вставки, які видно в цей проміжок часу."""
    return [
        i["box"] for i in items
        if i["box"] and i["fromSec"] < end and i["fromSec"] + i["durSec"] > start
    ]


def place(lines: list[dict], face: dict | None, index: int,
          blocks: list[dict] | None = None) -> tuple[dict, str, bool]:
    """Обирає зону для репліки: не на обличчі, не на вставці, не за краєм кадру."""
    block = measure(lines)
    bands = free_bands(face)
    if blocks:
        cut: dict[str, dict] = {}
        for name, band in bands.items():
            for k, piece in enumerate(split_band(band, blocks)):
                cut[name if k == 0 else f"{name}{k}"] = piece
        bands = cut

    # Чергуємо низ і верх, щоб репліки рухалися, а не стояли на місці.
    base = ["bottom", "top", "right", "left"] if index % 2 == 0 else ["top", "bottom", "left", "right"]
    order = [n for b in base for n in sorted(bands) if n == b or n.startswith(b)]

    fits = []
    for name in order:
        band = bands.get(name)
        if not band:
            continue
        s = fit_scale(block, band)
        if s is not None:
            fits.append((name, band, s))

    fitted = bool(fits)
    scale = 1.0
    if fits:
        # Смуги вже впорядковані за пріоритетом; серед тих, що дають повний
        # розмір, беремо першу, інакше ту, де текст доведеться стиснути найменше.
        full = [f for f in fits if f[2] == 1.0]
        name, band, scale = full[0] if full else max(fits, key=lambda f: f[2])
    elif bands:
        # Ніде не влізло навіть стиснутим — беремо найбільший вільний шматок і
        # стискаємо до його розміру, аби не вилізти за межі на обличчя.
        name, band = max(bands.items(), key=lambda kv: kv[1]["w"] * kv[1]["h"])
        scale = fit_scale(block, band) or SCALE_STEPS[-1]
    else:
        # Придатних смуг не лишилося. Спускаємося сходинками, і на кожній
        # обличчя лишається недоторканним — жертвуємо чим завгодно, крім нього.
        whole = {"x": SAFE_L, "w": UI_X - SAFE_L, "y": SAFE_T, "h": SAFE_B - SAFE_T}
        name = "fallback"
        band = None

        # 1) все безпечне поле, поріжене й обличчям, і сусідніми репліками
        tries = [list(blocks or []) + ([face] if face else [])]
        # 2) сусідні репліки — прикраса; перекриття з ними пробачаємо
        if blocks and face:
            tries.append([face])
        for obstacles in tries:
            pieces = [pc for pc in split_band(whole, obstacles) if pc["h"] >= 0.03]
            if pieces:
                band = max(pieces, key=lambda b: b["w"] * b["h"])
                break

        if band is None and face:
            # 3) обличчя з зазором з'їло все безпечне поле. Тоді беремо те, що
            # лишилося над ним або під ним, хай навіть смужку, і стискаємо текст.
            # Зазор обовʼязковий і тут: без нього смужка впиралася в саме
            # обличчя, і напис ставав упритул до підборіддя чи чола.
            above = {"x": SAFE_L, "w": UI_X - SAFE_L, "y": SAFE_T,
                     "h": max(face["y"] - FACE_GAP - SAFE_T, 0)}
            below_y = min(face["y"] + face["h"] + FACE_GAP, SAFE_B)
            below = {"x": SAFE_L, "w": UI_X - SAFE_L, "y": below_y,
                     "h": max(SAFE_B - below_y, 0)}
            # Ця смужка теж не має лізти під інтерфейс: ріжемо її перешкодами
            # й беремо найбільший вцілілий шматок.
            candidates = []
            for strip in (above, below):
                if strip["h"] <= 0:
                    continue
                candidates += split_band(strip, list(blocks or [])) or [strip]
            band = (max(candidates, key=lambda b: b["w"] * b["h"])
                    if candidates else max((above, below), key=lambda b: b["h"]))
            if band["h"] < 0.02:
                # Обличчя буквально на весь кадр. Останнє, що ще не є написом
                # на очах, — вузька смужка біля самого низу безпечного поля.
                band = {"x": SAFE_L, "w": UI_X - SAFE_L, "y": SAFE_B - 0.08, "h": 0.08}

        if band is None:
            band = whole   # обличчя немає взагалі — можна на весь кадр
        scale = fit_scale(block, band) or SCALE_STEPS[-1]

    align = ("center", "left", "right")[index % 3]
    # Вузькій смузі варіації не потрібні — там усе одно тісно.
    if band["w"] * FRAME_W < block["width"] * 1.25:
        align = "center"

    # Остання інстанція: хай би якою гілкою ми сюди дійшли, напис мусить бути в
    # межах своєї смуги. Затиск рахує масштаб точно, а не сходинками.
    scale = clamp_scale(block, band, scale)

    return ({"x": round(band["x"], 4), "y": round(band["y"], 4),
             "w": round(band["w"], 4), "h": round(band["h"], 4)},
            align, fitted, scale)


# Скільки місця просить вставка кожного типу (частки кадру).
INSERT_SIZE = {
    "number": (0.62, 0.24),
    "label": (0.70, 0.13),
    "image": (0.42, 0.24),
}


def place_insert(ins: dict, face: dict | None) -> dict | None:
    """Ставить вставку у вільну смугу — так само повз обличчя й краї."""
    want_w, want_h = INSERT_SIZE.get(ins.get("kind", "number"), (0.5, 0.2))
    bands = free_bands(face)
    order = ["top", "bottom", "right", "left"]
    for name in order:
        band = bands.get(name)
        if not band or band["h"] < want_h * 0.7 or band["w"] < want_w * 0.7:
            continue
        w = min(want_w, band["w"])
        h = min(want_h, band["h"])
        return {
            "x": round(band["x"] + (band["w"] - w) / 2, 4),
            "y": round(band["y"] + (band["h"] - h) / 2, 4),
            "w": round(w, 4),
            "h": round(h, 4),
        }
    return None


def build_inserts(spec: list[dict], args) -> list[dict]:
    """Розставляє вставки в кадрі, спираючись на те, де в цей момент обличчя."""
    if not spec:
        return []
    samples = []
    for s in spec:
        start, end = s["fromSec"], s["fromSec"] + s["durSec"]
        n = max(3, min(8, int((end - start) / 0.5) + 1))
        samples.append([start + (end - start) * k / (n - 1) for k in range(n)])
    flat = [ts for g in samples for ts in g]
    print(f"  розміщую {len(spec)} вставок (обличчя у {len(flat)} кадрах)…")
    raw = _faces.detect(args.source.resolve(), flat)
    filled = _faces.fill_gaps(raw)

    out, cursor = [], 0
    for s, group in zip(spec, samples):
        merged = _faces.union(filled[cursor:cursor + len(group)])
        cursor += len(group)
        face = _faces.padded(merged) if merged else None
        box = place_insert(s, face)
        if box is None:
            print(f"  ! вставці на {s['fromSec']}с не знайшлося вільного місця — пропускаю")
            continue
        out.append({**s, "box": box})
    return out


def pick_heroes(cues: list[list[dict]], every: float) -> set[int]:
    """Які репліки винести великими.

    Беремо найвагоміші за змістом, але не частіше ніж раз на `every` секунд —
    інакше «велике» перестає бути акцентом і кадр перетворюється на суцільний
    текст. Перша репліка йде великою завжди: це хук.
    """
    if not cues:
        return set()
    weight = [sum(salience(w["word"]) for w in c) for c in cues]
    order = sorted(range(len(cues)), key=lambda i: weight[i], reverse=True)

    # Хук: найвагоміша репліка з перших секунд, а не буквально перша. Інакше
    # великим виходить службовий обрубок на кшталт «У нас», а змістовне слово
    # лишається дрібним у наступній репліці.
    head = [i for i, c in enumerate(cues) if c[0]["start"] < max(every * 0.8, 3.0)] or [0]
    chosen: list[int] = [max(head, key=lambda i: weight[i])]
    for i in order:
        if i in chosen:
            continue
        start = cues[i][0]["start"]
        if all(abs(start - cues[j][0]["start"]) >= every for j in chosen):
            chosen.append(i)
    return set(chosen)


def build_kinetic(words: list[dict], brand: str, args, inserts: list[dict] | None = None) -> dict:
    cues = group_into_cues(words, args.max_words, args.gap, args.max_dur)
    lines_per_cue = [cue_to_lines(c) for c in cues]
    inserts = inserts or []
    two_tier = "hero" in LOOK_METRICS[args.look]
    heroes = pick_heroes(cues, args.hero_every) if two_tier else set()
    # Сліпі зони майданчика лежать поверх кадру весь час, тож додаються до
    # перешкод кожної репліки — нарівні з обличчям.
    zones = platform_zones(args.dest)
    if zones:
        print(f"  сліпі зони «{args.dest}»: {len(zones)}")

    faces: list[dict | None] = [None] * len(cues)
    if args.avoid_face and cues:
        # Три проби на репліку — початок, середина, кінець. Людина за дві секунди
        # встигає ворухнутися, тож зону обходу рахуємо по обʼєднанню трьох рамок.
        samples = []
        for c in cues:
            start, end = c[0]["start"], c[-1]["end"] + args.hold
            n = max(3, min(8, int((end - start) / 0.35) + 1))
            samples.append([start + (end - start) * k / (n - 1) for k in range(n)])
        flat = [ts for group in samples for ts in group]
        print(f"  шукаю обличчя у {len(flat)} кадрах ({len(cues)} реплік)…")
        raw = _faces.detect(args.source.resolve(), flat)
        found = sum(1 for f in raw if f)
        filled = _faces.fill_gaps(raw)
        faces, cursor = [], 0
        for group in samples:
            merged = _faces.union(filled[cursor:cursor + len(group)])
            cursor += len(group)
            faces.append(_faces.padded(merged) if merged else None)
        print(f"  обличчя знайдено в {found} із {len(flat)} кадрів")

    out = []
    placed: list[dict] = []          # уже розставлені репліки — теж перешкода
    for i, cue in enumerate(cues):
        lines = lines_per_cue[i]
        is_hero = i in heroes
        set_hero(is_hero)
        if args.avoid_face:
            span = (cue[0]["start"], cue[-1]["end"] + args.hold)
            # Репліки навмисно трохи перекриваються в часі, тож сусідня, яка ще
            # висить у кадрі, має обходитись так само, як обличчя чи вставка.
            hard = active_at(inserts, *span) + zones
            box, align, fitted, scale = place(lines, faces[i], i, hard + active_at(placed, *span))
            if not fitted:
                # Місця не лишилося. Перекриття сусідніх реплік — прикраса, а
                # «не на обличчі» — правило, тож жертвуємо прикрасою: підрізаємо
                # попередню репліку так, щоб вона зникла до появи цієї.
                trimmed = 0
                for prev in placed:
                    if prev["fromSec"] + prev["durSec"] > span[0] > prev["fromSec"]:
                        # мінус 0.05 с: інакше подвійне округлення часу лишає
                        # хвостик у частку кадру, і перевірка бачить накладання
                        prev["durSec"] = round(max(span[0] - prev["fromSec"] - 0.05, 0.5), 2)
                        out[prev["index"]]["durSec"] = prev["durSec"]
                        trimmed += 1
                if trimmed:
                    box, align, fitted, scale = place(lines, faces[i], i, hard + active_at(placed, *span))
            if is_hero and scale <= 0.7:
                # Місця для великого напису просто немає. Дрібний напис поруч з
                # обличчям кращий за великий на обличчі — знімаємо «велику» роль
                # і розкладаємо репліку звичайним розміром.
                is_hero = False
                set_hero(False)
                lines = lines_per_cue[i]
                box, align, fitted, scale = place(
                    lines, faces[i], i, hard + active_at(placed, *span)
                )
            x, y = round(box["x"] + box["w"] / 2, 4), round(box["y"] + box["h"] / 2, 4)
        else:
            box = None
            scale = 1.0
            x, y, align = ANCHORS[i % len(ANCHORS)]
        start, end = cue[0]["start"], cue[-1]["end"]
        entry = {
            "lines": lines,
            "fromSec": round(start, 2),
            "durSec": round(max(end - start + args.hold, 0.8), 2),
            "x": x,
            "y": y,
            "align": align,
        }
        if scale < 1.0:
            entry["scale"] = scale
        if is_hero:
            entry["hero"] = True
            # Велика фраза має встигнути прочитатися — тримаємо її трохи довше.
            entry["durSec"] = round(max(entry["durSec"], 1.4), 2)
        if box:
            entry["box"] = box
            placed.append({"fromSec": entry["fromSec"], "durSec": entry["durSec"],
                           "box": box, "index": len(out)})
        out.append(entry)
    set_hero(False)

    # Якою парою кольорів писати — вирішує сам кадр. Міряємо яскравість там, де
    # напис реально стоятиме, у середині його життя.
    if _luma.has_video(args.source.resolve()):
        measured = 0
        for entry in out:
            at = entry["fromSec"] + entry["durSec"] / 2
            dark = _luma.is_dark(args.source.resolve(), at, entry.get("box"))
            if dark is not None:
                entry["dark"] = dark
                measured += 1
        if measured:
            light = sum(1 for e in out if e.get("dark") is False)
            print(f"  яскравість кадру: {measured} реплік виміряно, з них на світлому — {light}")

    if args.look in ("quiet", "podcast"):
        # Слова не мають стрибати по кадру поодинці: тримаємо позицію групою
        # (кілька реплік поспіль в одному місці), а міняємо її лише коли група
        # добігла кінця або обличчя зрушило так, що стара зона більше не вільна.
        group_start = 0
        for i, cur in enumerate(out):
            if cur.get("hero"):
                group_start = i + 1   # велика фраза стоїть окремо
                continue
            anchor = out[group_start]
            if anchor.get("hero"):
                group_start = i
                continue
            same_zone = "box" in anchor and "box" in cur and boxes_overlap(anchor["box"], cur["box"])
            group_len = i - group_start
            # Позицію групи можна брати ТІЛЬКИ якщо вона вільна для цієї
            # репліки: обличчя за секунду встигає зрушити, і зона, що була
            # порожньою на початку групи, уже може бути на лиці. Це коштувало
            # чотирьох реплік поверх обличчя в «тихому» стилі.
            face_now = faces[i] if i < len(faces) else None
            anchor_clear = not (face_now and "box" in anchor
                                and boxes_overlap(anchor["box"], face_now))
            zones_clear = not any(boxes_overlap(anchor["box"], z) for z in zones) \
                if "box" in anchor else True
            if group_len >= QUIET_GROUP or not same_zone or not anchor_clear or not zones_clear:
                group_start = i
                continue
            cur["x"], cur["y"], cur["align"] = anchor["x"], anchor["y"], anchor["align"]
            cur["box"] = dict(anchor["box"])

        # У тихому стилі в кадрі живе рівно одне слово: наступне не має
        # зʼявлятися, доки попереднє ще не зникло.
        for cur, nxt in zip(out, out[1:]):
            room = round(nxt["fromSec"] - cur["fromSec"] - 0.05, 2)
            floor = 0.6 if cur.get("hero") else 0.25
            cur["durSec"] = round(max(min(cur["durSec"], room), floor), 2)

    # Контроль наостанок: обличчя — це правило, а не побажання. Якщо після всіх
    # гілок якась репліка все ж перетинає рамку обличчя, це помилка розкладки,
    # і краще побачити її в журналі, ніж у готовому ролику.
    if args.avoid_face:
        on_face = [
            (out[i]["fromSec"], faces[i])
            for i in range(len(out))
            if "box" in out[i] and faces[i] and boxes_overlap(out[i]["box"], faces[i])
        ]
        if on_face:
            print(f"  ! УВАГА: {len(on_face)} реплік перетинають обличчя "
                  f"(перша на {on_face[0][0]}с)")
        else:
            print(f"  обличчя чисте: жодна з {len(out)} реплік його не перекриває")

    if zones:
        blind = [c["fromSec"] for c in out
                 if "box" in c and any(boxes_overlap(c["box"], z) for z in zones)]
        if blind:
            print(f"  ! УВАГА: {len(blind)} реплік у сліпій зоні "
                  f"(перша на {blind[0]}с) — їх не буде видно під інтерфейсом")
        else:
            print("  сліпі зони чисті: жодна репліка під інтерфейс не потрапила")

    # Контроль межі кадру. Репліка може бути й не на обличчі, і не під
    # інтерфейсом, і все одно вилітати за край — якщо блок ширший за свою смугу.
    # Тут ми переміряємо вже ГОТОВІ репліки їхнім власним масштабом.
    over = []
    tight = []
    for i, cue in enumerate(out):
        if "box" not in cue:
            continue
        set_hero(bool(cue.get("hero")))
        block = measure(cue["lines"])
        sc = cue.get("scale", 1.0)
        w_px = cue["box"]["w"] * FRAME_W
        h_px = cue["box"]["h"] * FRAME_H
        if block["longest_word"] * sc > w_px + 1 or wrapped_height(block, w_px, sc) > h_px + 1:
            over.append(cue["fromSec"])
        elif sc < 0.55:
            tight.append(cue["fromSec"])
    set_hero(False)
    if over:
        print(f"  ! УВАГА: {len(over)} реплік не вміщуються у свою смугу "
              f"(перша на {over[0]}с) — вони вилізуть за край")
    else:
        print(f"  межі кадру чисті: усі {len(out)} реплік у своїх смугах")
    if tight:
        print(f"  (дрібним набрано {len(tight)} реплік — місця було обмаль; "
              f"перша на {tight[0]}с)")

    return {"brand": brand, "look": args.look, "accentColor": args.accent_color,
            "edge": args.edge, "cues": out, "overlay": True, "showSafeGuides": False}


def build_script(words: list[dict], brand: str, args) -> dict:
    """Один статичний кадр із перших слів — для обкладинки або хука."""
    cues = group_into_cues(words, args.max_words, args.gap, args.max_dur)
    first = cues[0] if cues else []
    return {
        "brand": brand,
        "look": args.look,
        "edge": args.edge,
        "lines": cue_to_lines(first),
        "verticalAnchor": 0.5,
        "showSafeGuides": False,
        "overlay": False,
    }


def build_reel(words: list[dict], brand: str, args) -> dict:
    """Ті самі репліки, але поверх вихідного відео (композиція KineticReel)."""
    spec = []
    if args.inserts:
        spec = json.loads(Path(args.inserts).read_text(encoding="utf-8"))
    if args.library:
        catalog = _library.sync()
        found = _library.match(words, catalog)
        if found:
            print(f"  каталог: {len(catalog)} файлів, збіглося {len(found)}")
            for f in found:
                print(f"      «{f['_word']}» на {f['fromSec']}с → {Path(f['src']).name}")
            _library.stage(found, PROJECT / "public")
        else:
            print(f"  каталог: {len(catalog)} файлів, жодне ключове слово не прозвучало")
        spec = spec + [{k: v for k, v in f.items() if k != "_word"} for f in found]
    inserts = build_inserts(spec, args) if spec else []
    kinetic = build_kinetic(words, brand, args, inserts)
    return {
        "brand": brand,
        "look": args.look,
        "accentColor": args.accent_color,
        "edge": args.edge,
        "videoSrc": args.video_src or args.source.name,
        "startInSeconds": 0,
        "muted": False,
        "cues": kinetic["cues"],
        "inserts": inserts,
        "showSafeGuides": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="аудіо або відео файл")
    ap.add_argument("--brand", default="default",
                    help="бренд із engine/src/brands (типово «default»)")
    ap.add_argument("--mode", default="kinetic", choices=["kinetic", "script", "reel"],
                    help="kinetic — субтитри окремим шаром; reel — поверх самого відео; script — один статичний кадр")
    ap.add_argument("--cut-fillers", action="store_true", dest="cut_fillers",
                    help="вирізати слова-паразити з короткого безпечного списку")
    ap.add_argument("--cut-pauses", type=float, default=None, dest="cut_pauses",
                    help="вирізати паузи, довші за вказану кількість секунд")
    ap.add_argument("--cut-list", default=None, dest="cut_list",
                    help="JSON зі списком [[початок, кінець], …] — що вирізати вручну")
    ap.add_argument("--library", action="store_true",
                    help="брати вставки з каталогу за збігом ключових слів у тексті")
    ap.add_argument("--inserts", default=None,
                    help="JSON зі списком вставок: fromSec, durSec, kind, text/caption/src")
    ap.add_argument("--speed", type=float, default=None,
                    help="пришвидшити відео (1.25, 1.3…): час стискається, висота голосу лишається")
    ap.add_argument("--no-avoid-face", action="store_false", dest="avoid_face",
                    help="не шукати обличчя — розкладати репліки старими якорями")
    ap.add_argument("--video-src", default=None, dest="video_src",
                    help="імʼя файлу в public/ для режиму reel (типово — імʼя вихідного файлу)")
    ap.add_argument("--model", default="large-v3",
                    choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
                    help="за замовчуванням large-v3: на українській він і точніший, і швидший за medium")
    ap.add_argument("--language", default="uk")
    ap.add_argument("--look", default="editorial", choices=list(LOOKS),
                    help="характер субтитрів: editorial — золото й капс, "
                         "quiet — тихе біле малими (одне слово в кадрі), "
                         "bold — білий капс із жовтим ключовим словом, "
                         "calligraphy — велика каліграфія Great Vibes і капс, "
                         "classic — дідонівський серіф: курсив і капс, "
                         "podcast — дрібне біле плюс великі ключові фрази")
    ap.add_argument("--dest", default="reels",
                    choices=["reels", "stories", "tiktok", "shorts", "linkedin", "none"],
                    help="майданчик: його інтерфейс (колонка іконок, підпис, таймлайн) "
                         "стає забороненою зоною для тексту")
    ap.add_argument("--edge", default="halo", choices=["halo", "shadow", "none"],
                    help="що під літерами: halo — темний ореол і тінь (типово), "
                         "shadow — сама мʼяка тінь, none — нічого")
    ap.add_argument("--audio-fix", action="store_true", dest="audio_fix",
                    help="вирівняти гучність голосу до -14 LUFS (стандарт стрічки)")
    ap.add_argument("--color-fix", action="store_true", dest="color_fix",
                    help="делікатна кольорокорекція: контраст, насиченість, різкість")
    ap.add_argument("--accent-color", default=None, dest="accent_color",
                    help="чим підсвічувати ключове слово, напр. #660033. "
                         "Світлу пару для темних кадрів композиція порахує сама. "
                         "Типово — акцент, зашитий у стилі")
    ap.add_argument("--hero-every", type=float, default=5.0, dest="hero_every",
                    help="як часто (в секундах) виносити ключову фразу великою — "
                         "лише для стилів із двома поверхами (podcast)")
    ap.add_argument("--max-words", type=int, default=None, dest="max_words",
                    help="максимум слів у одній репліці (типово 5; quiet — 1, podcast — 2)")
    ap.add_argument("--gap", type=float, default=0.35,
                    help="пауза в секундах, після якої починається нова репліка")
    ap.add_argument("--max-dur", type=float, default=2.6, dest="max_dur",
                    help="максимальна довжина репліки в секундах")
    ap.add_argument("--hold", type=float, default=0.35,
                    help="скільки секунд репліка ще висить після останнього слова")
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()

    # Характер субтитрів визначає і метрики розкладки, і скільки слів тримати
    # в кадрі: «тихий» стиль живе одним словом, решта — реплікою до пʼяти.
    set_look(args.look)
    if args.max_words is None:
        args.max_words = {"quiet": 1, "podcast": 2}.get(args.look, 5)

    if not args.source.exists():
        sys.exit(f"Немає такого файлу: {args.source}")

    print(f"→ Транскрибую {args.source.name} (модель {args.model}, мова {args.language})…")
    words = transcribe(args.source.resolve(), args.model, args.language)
    raw_count = len(words)
    words = merge_fragments(words)
    glued = raw_count - len(words)
    print(f"  розпізнано слів: {len(words)}" + (f" (склеєно уламків: {glued})" if glued else ""))

    spans = []
    if args.cut_list:
        spans += [tuple(s[:2]) for s in json.loads(Path(args.cut_list).read_text(encoding="utf-8"))]
    if args.cut_fillers:
        spans += _cuts.filler_spans(words)
    if args.cut_pauses:
        spans += _cuts.pause_spans(words, args.cut_pauses)
    if spans:
        spans = _cuts.merge_spans(spans)
        cut_file = args.source.resolve().parent / f"{args.source.stem}-cut.mp4"
        print(f"→ Вирізаю {len(spans)} шматків, разом {_cuts.total(spans):.1f} с…")
        _cuts.apply(args.source.resolve(), spans, cut_file, source_fps(args.source.resolve()))
        before = len(words)
        words = _cuts.remap(words, spans)
        print(f"  ✓ {cut_file.name} — слів лишилося {len(words)} із {before}")
        # далі все — обличчя, вставки, субтитри — рахуємо вже по обрізаному
        args.source = cut_file
        if not args.video_src:
            args.video_src = cut_file.name

    builders = {"kinetic": build_kinetic, "script": build_script, "reel": build_reel}
    props = builders[args.mode](words, args.brand, args)

    if args.speed and args.speed != 1.0:
        if args.speed < 1.0 or args.speed > 2.0:
            sys.exit("--speed має бути в межах 1.0–2.0")
        # Розпізнавання й пошук обличчя робимо на оригіналі — там точніше, — а
        # вже готові таймінги стискаємо. Кадри збігаються один в один.
        for c in props.get("cues", []) + props.get("inserts", []):
            c["fromSec"] = round(c["fromSec"] / args.speed, 2)
            c["durSec"] = round(max(c["durSec"] / args.speed, 0.4), 2)
        if args.mode == "reel":
            fast = speed_up(args.source.resolve(), args.speed, args.source.resolve().parent)
            props["videoSrc"] = fast.name

    if (args.audio_fix or args.color_fix) and args.mode == "reel":
        # Робимо останнім кроком, уже на тому файлі, який піде в рендер: і на
        # обрізаному, і на пришвидшеному. Геометрію не чіпаємо, тож розкладка
        # реплік лишається чинною.
        src = args.source.resolve().parent / props["videoSrc"]
        if not src.exists():
            src = args.source.resolve()
        done = polish(src, src.parent, args.audio_fix, args.color_fix)
        props["videoSrc"] = done.name

    out = args.out or DATA_DIR / f"{args.source.stem}.captions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")

    comps = {"kinetic": "KineticCaptions", "reel": "KineticReel", "script": "ScriptCaption"}
    n = len(props["lines"]) if args.mode == "script" else len(props["cues"])
    print(f"✓ {out}")
    print(f"  {'рядків' if args.mode == 'script' else 'реплік'}: {n}")
    if args.mode == "reel":
        print(f"  ! поклади відео в public/{props['videoSrc']}")
    print()
    print("Далі:")
    print("  npx remotion studio")
    print(f"  → композиція {comps[args.mode]}")
    print(f"  → вставити props із {out.name} і вичитати текст (Whisper помиляється на іменах і термінах)")


if __name__ == "__main__":
    main()
