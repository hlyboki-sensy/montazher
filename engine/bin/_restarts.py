"""Обмовки й перезапуски фрази: знайти, зважити, показати, вирізати.

Головне, що треба знати про цю задачу: **Whisper стирає перезапуски з тексту**.
Перевірено на зразках — з чотирьох випадків дубль зник у трьох. Модель навчена
віддавати гладкий субтитровий текст, тому пошук повторів у словах ловить
меншість. Реальний слід дефекту лежить у часі й у звуці:

  · слово, що проглинуло дубль, триває 1,7-3,3 с замість 0,3-0,6;
  · у точці, де людина обірвалася, гучність падає на 13 дБ за десятки
    мілісекунд, тоді як нормальне закінчення слова дає 3-5 дБ.

`probability` для цього не годиться взагалі: слово, яке проглинуло уламок,
паузу й другу спробу, мало p = 0,93. Ця цифра говорить про рідкість слова, а
не про якість вимови.

Каскад: спершу безплатні текстові генератори кандидатів, потім акустика ТІЛЬКИ
на знайдених місцях, потім бали. Вирок: ≥ 4 різати · 2-3 показати людині ·
менше 2 лишити.
"""

from __future__ import annotations

import difflib
import json
import math
from pathlib import Path

from _prosody import SPEECH_DB, Voice, corr_contours

VOWELS = set("аеєиіїоуюяАЕЄИІЇОУЮЯ")
TRIM = " ,.!?…:;—-«»\"'()"

# Службові й короткі слова вимовляються швидше за будь-яку модель тривалості.
# Без цього списку «обірваними» вважаються «в», «не», «як», «те» — тобто майже
# кожна фраза.
FUNCTION_WORDS = {
    "і", "й", "та", "а", "але", "бо", "що", "як", "це", "цей", "ця", "те",
    "то", "у", "в", "з", "із", "зі", "на", "до", "за", "по", "від", "для",
    "про", "при", "над", "під", "без", "не", "ні", "ж", "би", "б", "же",
    "я", "ти", "ви", "ми", "він", "вона", "воно", "вони", "мене", "тебе",
    "вам", "нам", "їх", "його", "її", "мій", "моя", "ваш", "наш", "так",
    "ось", "от", "ну", "вже", "ще", "тут", "там", "коли", "чи", "або",
    "себе", "собі", "нас", "вас", "їм", "ним", "нею", "де", "куди", "хоч",
}

# Чергування сидять у КІНЦІ українського кореня, тому згортаємо хвіст.
TAIL_SWAPS = [("ськ", "ск"), ("зьк", "зк"), ("ц", "к"), ("з", "г"),
              ("с", "х"), ("ж", "г"), ("ч", "к"), ("ш", "х"), ("щ", "ск")]
ENDINGS = ("ами", "ями", "ові", "еві", "ої", "ий", "ій", "ою", "ею", "ти",
           "ть", "ла", "ло", "ли", "ів", "ам", "ям", "ах", "ях", "ом", "ем",
           "ей", "у", "ю", "а", "я", "и", "і", "е", "о")

# Пороги. Ті, що зміряні на зразках, підписані числом із заміру; ті, що взяті
# з літератури, підписані джерелом — їх і треба рухати першими, якщо метод
# почне помилятися.
RATIO_LONG = 1.8      # зміряно: чисті слова до 1,53, дефект від 3,39
RATIO_SHORT = 0.62    # зміряно: чисті слова від 0,63
SILENCE = 0.18        # зміряно: чисті 0,04 с, дефект 0,51-1,30 с
# Верхня межа не менш важлива за нижню. Обмовка — це швидке спотикання; коли
# тиша довша за 0,6 с, людина думає, а не збивається, і цим уже займається
# окрема галочка «прибрати довгі паузи». Без цієї межі детектор позначав
# дефектом кожну задуму в записі.
SILENCE_MAX = 0.6
DROP_DB = 8.0         # зміряно на зразках: норма до 5,5 дБ, обрив від 13 дБ
# На живому запису з телефона 16% УСІХ слів дають провал ≥ 8 дБ — тобто абсолютний
# поріг зі зразків туди не переноситься. Тому поріг рахується від самого
# запису: береться 95-й відсоток провалів по всіх словах, але не нижче 8 дБ.
# Так само самокалібрується модель тривалості — це той самий прийом.
DROP_PCTL = 95
HNR_DEAD = 10.0       # з літератури, під диктора перевіряється окремо
DUR_RATIO = 1.25      # напрямок із літератури, величина — ні
CORR_INTENT = -0.3    # Shriberg: навмисний повтор дає негативну кореляцію
CUT_SCORE = 4         # вирок «різати»
SHOW_SCORE = 2        # вирок «показати людині»
MAX_SHOW = 15         # більше — метод скоріше промахнувся, список не показуємо

PAD_LEFT = 0.06       # повітря ліворуч від різу
PAD_RIGHT = 0.08      # праворуч треба більше — асиметрія навмисна
SNAP = 0.08           # різ зсувається до тиші в межах ±80 мс


# ── текст ────────────────────────────────────────────────────────────────────

def syllables(word: str) -> int:
    return max(1, sum(c in VOWELS for c in word))


def bare(word: str) -> str:
    return word.strip(TRIM).lower()


def stem(word: str) -> str:
    w = bare(word)
    if len(w) <= 3:
        return w
    for end in ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= 3:
            w = w[: -len(end)]
            break
    if w.endswith("л") and len(w) > 3 and w[-2] in "бпвмф":
        w = w[:-1]                       # вставне «л»: роблю → роб
    for a, b in TAIL_SWAPS:
        if w.endswith(a):
            w = w[: -len(a)] + b
            break
    return w


def same_word(a: str, b: str) -> bool:
    """Дві форми одного слова.

    Свідомо БЕЗ префіксного правила: на зразках воно не додало повноти, зате
    підняло хибні збіги з 8% до 15%.
    """
    sa, sb = stem(a), stem(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    return difflib.SequenceMatcher(None, sa, sb).ratio() >= 0.90


def duration_model(words: list[dict]) -> tuple[float, float]:
    """Своя модель тривалості на кожен файл: темп у кожному записі інший.

    Найдовші 20% викидаємо — саме серед них і сидять дефекти, які ми шукаємо,
    інакше вони потягнуть модель на себе.
    """
    rows = [(syllables(bare(w["word"])), w["end"] - w["start"])
            for w in words if bare(w["word"]) not in FUNCTION_WORDS]
    rows = [(s, d) for s, d in rows if d > 0]
    if len(rows) < 8:
        return 0.142, 0.081
    rows.sort(key=lambda r: r[1])
    clean = rows[: int(len(rows) * 0.8)] or rows
    n = len(clean)
    sx = sum(s for s, _ in clean)
    sy = sum(d for _, d in clean)
    sxx = sum(s * s for s, _ in clean)
    sxy = sum(s * d for s, d in clean)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.142, 0.081
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return (a, b) if a > 0 else (0.142, 0.081)


# ── ступінь 1: кандидати з тексту й таймкодів ────────────────────────────────

def _candidates(words: list[dict], voice: Voice) -> list[dict]:
    a, b = duration_model(words)
    expect = lambda t: a * syllables(t) + b
    out: list[dict] = []

    for i, w in enumerate(words):
        t = bare(w["word"])
        dur = w["end"] - w["start"]
        exp = expect(t)
        ratio = dur / exp if exp > 0 else 1.0

        # A. розпухлий токен — усередині сховані уламок, пауза й друга спроба.
        if ratio >= RATIO_LONG and dur >= 0.55:
            isl = voice.islands(w["start"] - 0.05, w["end"] + 0.05)
            # Один острівець означає «слово, а далі звичайна пауза». Без цієї
            # перевірки детектор давав два десятки хибних знахідок на хвилину.
            gap = isl[1][0] - isl[0][1] if len(isl) >= 2 else 0.0
            if len(isl) >= 2 and SILENCE <= gap <= SILENCE_MAX and isl[-1][1] - isl[-1][0] >= 0.15:
                out.append({"kind": "swollen", "index": i, "ratio": ratio,
                            "at": w["start"], "to": w["end"],
                            "break_at": isl[0][1], "first": isl[0], "second": isl[-1],
                            "text": w["word"].strip()})
            continue

        # B. обірване слово — закоротке для своїх складів.
        if ratio <= RATIO_SHORT and t not in FUNCTION_WORDS and len(t) > 3:
            nxt = words[i + 1]["start"] if i + 1 < len(words) else w["end"] + 0.3
            prev = words[i - 1]["end"] if i else max(0.0, w["start"] - 0.3)
            out.append({"kind": "fragment", "index": i, "ratio": ratio,
                        "at": w["start"], "to": w["end"], "break_at": w["end"],
                        "first": (w["start"], w["end"]), "second": (nxt, nxt),
                        "prev_end": prev, "next_start": nxt,
                        "text": w["word"].strip()})

    # C. повтор упритул — та сама послідовність двічі без думки між спробами.
    for i in range(len(words) - 1):
        for n in range(4, 0, -1):
            j = i + n
            if j + n > len(words):
                continue
            first = [bare(x["word"]) for x in words[i:j]]
            second = [bare(x["word"]) for x in words[j:j + n]]
            if not all(first) or not all(second):
                continue
            if words[j]["start"] - words[j - 1]["end"] > 2.0:
                continue
            if all(same_word(x, y) for x, y in zip(first, second)):
                out.append({
                    "kind": "repeat", "index": i, "words_matched": n,
                    "at": words[i]["start"], "to": words[j + n - 1]["end"],
                    "break_at": words[j - 1]["end"],
                    "first": (words[i]["start"], words[j - 1]["end"]),
                    "second": (words[j]["start"], words[j + n - 1]["end"]),
                    "prev_end": words[i - 1]["end"] if i else words[i]["start"],
                    "next_start": words[j]["start"],
                    "text": " ".join(x["word"].strip() for x in words[i:j + n]),
                })
                break

    out.sort(key=lambda c: c["at"])
    return out


# ── ступінь 2-3: акустика на кандидатах і бали ───────────────────────────────

def _creak_is_style(words: list[dict], voice: Voice) -> bool:
    """Чи скрипучий хвіст — це просто манера диктора, а не ознака обриву.

    Частина голосів завершує кожну фразу скрипом. Якщо таких завершень більше
    пʼятої частини, ознака для цього запису важить нуль — інакше вона
    позначить дефектом половину ролика.
    """
    ends = [w for w in words if w["end"] - w["start"] > 0.2][:120]
    if len(ends) < 20:
        return False
    dead = 0
    for w in ends:
        h = voice.tail_hnr(max(w["start"], w["end"] - 0.08), w["end"])
        if h != h or h <= HNR_DEAD:
            dead += 1
    return dead > 0.2 * len(ends)


def _drop_reference(words: list[dict], voice: Voice) -> float:
    """Поріг провалу енергії саме для цього голосу й цього мікрофона.

    Абсолютні 8 дБ зі зразків на живому записі позначають дефектом кожне шосте
    слово. Тому за норму беремо сам запис: обривом вважаємо те, що голосніше
    за 95% звичайних завершень слів у цьому ж файлі.
    """
    import numpy as np
    vals = [voice.drop_at_end(max(w["start"], w["end"] - 0.35), w["end"]) for w in words]
    if len(vals) < 30:
        return DROP_DB
    return max(DROP_DB, float(np.percentile(vals, DROP_PCTL)))


def _score(c: dict, voice: Voice, creak_blind: bool, drop_ref: float) -> dict:
    tb = c["break_at"]
    f_a, f_b = c["first"]
    s_a, s_b = c["second"]
    plus: list[str] = []
    minus: list[str] = []
    score = 0

    # 1. тиша в місці обриву
    if c["kind"] == "swollen":
        silence = voice.longest_silence(c["at"] - 0.05, c["to"] + 0.05)
    else:
        silence = max(0.0, s_a - tb)
    if SILENCE <= silence <= SILENCE_MAX:
        score += 2
        plus.append(f"тиша {silence:.2f} с")

    # 2. провал енергії — найнадійніша ознака
    drop = voice.drop_at_end(max(f_a, tb - 0.35), tb)
    if drop >= drop_ref:
        score += 2
        plus.append(f"обрив енергії {drop:.0f} дБ")

    # 3. мертвий хвіст: неозвучений або скрипучий
    voiced = voice.voiced_fraction(max(f_a, tb - 0.08), tb)
    hnr = voice.tail_hnr(max(f_a, tb - 0.08), tb)
    if not creak_blind and (voiced < 0.35 or (hnr == hnr and hnr <= HNR_DEAD)):
        score += 2
        plus.append("хвіст згас")

    # 4. друга спроба довша за покинуту
    d1, d2 = max(f_b - f_a, 1e-3), max(s_b - s_a, 0.0)
    ratio = d2 / d1
    if c["kind"] == "repeat" and ratio >= DUR_RATIO:
        score += 2
        plus.append("друга спроба довша")

    # 5. висота не дійшла до цілі
    tail = voice.contour(max(f_a, tb - 0.20), tb)
    if tail.size >= 4:
        slope = float(tail[-1] - tail[0])
        if slope <= -3.0 and drop >= drop_ref / 2:
            score += 1
            plus.append("голос обірвався на спаді")

    # 6. сама аномалія тривалості
    if c.get("ratio") and (c["ratio"] >= RATIO_LONG or c["ratio"] <= RATIO_SHORT):
        score += 1
        plus.append(f"тривалість ×{c['ratio']:.1f} від норми")

    # ── проти: ознаки навмисності ───────────────────────────────────────────
    corr = float("nan")
    if c["kind"] != "fragment" and d2 > 0.05:
        corr = corr_contours(voice.contour(f_a, f_b), voice.contour(s_a, s_b))
    if corr == corr and corr <= CORR_INTENT:
        score -= 2
        minus.append("контури розбіжні — схоже на перелік")

    if c["kind"] == "repeat" and c.get("third_equal"):
        score -= 2
        minus.append("рівний ритм переліку")

    loud1 = voice.loudness(f_a, f_b)
    loud2 = voice.loudness(s_a, s_b) if d2 > 0.03 else loud1
    if c["kind"] != "fragment" and loud2 < loud1 - 1.0 and d2 < d1:
        score -= 1
        minus.append("друга спроба тихіша й коротша")

    # запобіжник від емфази: «Це важливо. Це — ВАЖЛИВО.»
    f1 = voice.median_f0(f_a, f_b)
    f2 = voice.median_f0(s_a, s_b) if d2 > 0.05 else float("nan")
    semis = 12.0 * math.log2(f2 / f1) if (f1 == f1 and f2 == f2 and f1 > 0) else float("nan")
    if loud2 >= loud1 + 3.0 and semis == semis and semis >= 3.0 and drop < drop_ref:
        score -= 3
        minus.append("це наголос, а не обмовка")

    c.update({"score": score, "plus": plus, "minus": minus, "silence": silence,
              "drop": drop, "dur_ratio": ratio, "corr": corr})
    return c


# ── різи ─────────────────────────────────────────────────────────────────────

def _snap(voice: Voice, t: float) -> float:
    """Зсуває різ до найближчого тихого кадру в межах ±80 мс.

    Різ посеред озвученої ділянки чути як клац, навіть коли текст ідеальний.
    """
    seg = voice.slice_db(t - SNAP, t + SNAP)
    if seg.size == 0:
        return t
    quiet = [k for k, v in enumerate(seg) if v <= SPEECH_DB]
    if quiet:
        mid = len(seg) / 2
        k = min(quiet, key=lambda q: abs(q - mid))
    else:
        # Тиші поруч немає — тоді беремо найтихіший кадр вікна. Різ у локальному
        # мінімумі енергії все одно чути набагато менше, ніж різ посеред голосної.
        k = int(seg.argmin())
    return round(max(0.0, t - SNAP + k * voice.hop_sec), 3)


def _span(c: dict, voice: Voice) -> tuple[float, float] | None:
    if c["kind"] == "repeat":
        left = c["prev_end"] + PAD_LEFT
        right = c["next_start"] - PAD_RIGHT
    elif c["kind"] == "swollen":
        left = c["first"][1] + PAD_LEFT
        right = c["second"][0] - PAD_RIGHT
    else:                                    # fragment
        left = max(c["prev_end"] + PAD_LEFT, c["at"] - PAD_LEFT)
        right = c["next_start"] - PAD_RIGHT
    left, right = _snap(voice, left), _snap(voice, right)
    return (round(left, 3), round(right, 3)) if right - left > 0.08 else None


def _confident(c: dict) -> bool:
    """Купка високої впевненості — та, яку можна різати без питань.

    Для повтору чотири умови разом: збіг від трьох слів (на двох українська
    дає надто багато законних фігур), пауза тишею до 2 с, покинута спроба не
    довша за 12 слів, друга спроба не коротша за першу.
    """
    # Самостійно ріжемо ЛИШЕ повтор, видимий у тексті: там навіть при помилці
    # акустики очі бачать дослівний дубль. Розпухлий токен і уламок видно тільки
    # приладу, тому вони завжди йдуть людині на перегляд, хай там які бали.
    if c["kind"] != "repeat":
        return False
    ok = (c.get("words_matched", 0) >= 3       # на двох словах українська дає надто багато законних фігур
          and c["silence"] <= 2.0              # навмисний повтор розділений мовленням, а не тишею
          and c.get("words_matched", 0) <= 12  # покинута спроба не буває довгою
          and c["dur_ratio"] >= 0.95)          # друга спроба не коротша за першу
    # Будь-яка ознака навмисності знімає автоматичний різ: розбіжні контури,
    # рівний ритм переліку, наголос. Краще спитати, ніж зрізати фігуру мови.
    return ok and not c["minus"]


# ── вхідна точка ─────────────────────────────────────────────────────────────

def analyse(words: list[dict], video: Path, work: Path) -> dict:
    """Повертає {cut, show, keep, spans, creak_blind} — без жодного різання."""
    from _prosody import extract_wav

    wav = extract_wav(video, work / f".{video.stem}.16k.wav")
    voice = Voice(wav)
    creak_blind = _creak_is_style(words, voice)

    drop_ref = _drop_reference(words, voice)
    cands = [_score(c, voice, creak_blind, drop_ref) for c in _candidates(words, voice)]
    for c in cands:
        c["span"] = _span(c, voice)
        c["context"] = _context(words, c["index"])
    # Різ коротший за 0,15 с нічого не прибирає, зате лишає по собі клац.
    cands = [c for c in cands if c["span"] and c["span"][1] - c["span"][0] >= 0.15]

    cut = [c for c in cands if _confident(c)]
    show = [c for c in cands if not _confident(c) and c["score"] >= SHOW_SCORE]
    keep = [c for c in cands if c["score"] < SHOW_SCORE]
    return {"cut": cut, "show": show, "keep": keep, "creak_blind": creak_blind,
            "drop_ref": drop_ref, "spans": [c["span"] for c in cut]}


def _context(words: list[dict], idx: int, span: int = 4) -> str:
    lo, hi = max(0, idx - span), min(len(words), idx + span + 1)
    return " ".join(w["word"].strip() for w in words[lo:hi])


def _stamp(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


def report(res: dict, dest: Path | None = None, cutting: bool = True) -> str:
    """Список для людини. Ніколи не мовчить: підсумковий рядок є завжди, навіть коли нулі."""
    cut, show, keep = res["cut"], res["show"], res["keep"]
    if cutting:
        lines = [f"Обмовки: вирізала {len(cut)}, лишила недоторканими {len(show) + len(keep)}."]
    else:
        lines = [f"Обмовки: знайшла дослівних повторів {len(cut)}, спірних місць {len(show)}. "
                 f"Нічого не різала — лише подивилася."]
    if res["creak_blind"]:
        lines.append("(скрипучий хвіст у цьому записі — манера голосу, за ознаку не рахувала)")
    if cut:
        lines.append("")
        lines.append("Вирізано:" if cutting else "Дослівні повтори — скажи слово, і виріжу:")
        for c in cut:
            lines.append(f"  {_stamp(c['at'])}  −{c['span'][1] - c['span'][0]:.1f} с   …{c['context']}…")
    if len(show) > MAX_SHOW:
        lines.append("")
        lines.append(f"Спірних місць {len(show)} — це підозріло багато, метод скоріше "
                     f"промахнувся. Нічого з них не чіпала; скажи, якщо показати пʼять найочевидніших.")
    elif show:
        lines.append("")
        lines.append("Перевір ці — сама не вирішила:")
        for n, c in enumerate(sorted(show, key=lambda x: -x["score"]), 1):
            why = ", ".join(c["plus"][:2]) or "схоже на збій"
            lines.append(f"  {n}. {_stamp(c['at'])}  −{c['span'][1] - c['span'][0]:.1f} с   {why}")
            lines.append(f"     лишається: …{c['context']}…")
    if keep:
        lines.append("")
        lines.append("Лишила як живу мову: " + ", ".join(_stamp(c["at"]) for c in keep[:12])
                     + (" …" if len(keep) > 12 else ""))
    text = "\n".join(lines)
    if dest:
        dest.write_text(text + "\n", encoding="utf-8")
    return text


def dump(res: dict, dest: Path) -> None:
    """Повні дані кандидатів — щоб потім можна було перерахувати пороги."""
    rows = []
    for bucket in ("cut", "show", "keep"):
        for c in res[bucket]:
            rows.append({"вирок": bucket, "тип": c["kind"], "час": round(c["at"], 2),
                         "бали": c["score"], "тиша": round(c["silence"], 3),
                         "провал_дБ": round(c["drop"], 1),
                         "відношення": round(c["dur_ratio"], 2),
                         "кореляція": None if c["corr"] != c["corr"] else round(c["corr"], 2),
                         "за": c["plus"], "проти": c["minus"],
                         "різ": c["span"], "текст": c["context"]})
    dest.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
