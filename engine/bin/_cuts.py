"""Вирізання шматків із відео з перерахунком таймінгів слів.

Whisper дає час кожного слова, тож вирізати «ну» на 129.52–129.71 — це
арифметика. Складніше інше: після різання весь подальший час зсувається, і
субтитри треба перерахувати. Цим і займається цей модуль.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Слова, які майже завжди сміття. Свідомо КОРОТКИЙ список: «там», «отже»,
# «просто» сюди не входять, бо в українській вони частіше несуть зміст
# («там, де ви мовчали»), і сліпе різання ламає речення.
SAFE_FILLERS = {"ну", "еее", "ммм", "емм", "тіпа", "типу"}

TRIM = " ,.!?…:;—-«»\"'()"


def merge_spans(spans: list[tuple[float, float]], glue: float = 0.12) -> list[tuple[float, float]]:
    """Склеює сусідні вирізи, між якими лишається зовсім мало."""
    if not spans:
        return []
    spans = sorted(spans)
    out = [list(spans[0])]
    for a, b in spans[1:]:
        if a - out[-1][1] <= glue:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def pause_spans(words: list[dict], threshold: float, keep: float = 0.18) -> list[tuple[float, float]]:
    """Паузи, довші за поріг. Лишаємо трохи повітря, щоб мова не злиплася."""
    spans = []
    for i in range(len(words) - 1):
        gap = words[i + 1]["start"] - words[i]["end"]
        if gap > threshold:
            spans.append((words[i]["end"] + keep / 2, words[i + 1]["start"] - keep / 2))
    return [s for s in spans if s[1] - s[0] > 0.05]


def filler_spans(words: list[dict], extra: set[str] | None = None) -> list[tuple[float, float]]:
    """Слова-паразити зі свідомо короткого списку."""
    vocab = SAFE_FILLERS | (extra or set())
    spans = []
    for i, w in enumerate(words):
        bare = w["word"].strip(TRIM).lower()
        if bare in vocab:
            # прихоплюємо паузу перед словом, щоб не лишався провал
            start = w["start"]
            if i > 0:
                start = max(words[i - 1]["end"], w["start"] - 0.12)
            spans.append((start, w["end"]))
    return spans


def total(spans: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in spans)


def remap(words: list[dict], spans: list[tuple[float, float]]) -> list[dict]:
    """Перераховує час слів так, ніби вирізаного ніколи не було."""
    spans = merge_spans(spans)
    out = []
    for w in words:
        # слово повністю всередині вирізу — його більше немає
        if any(a <= w["start"] and w["end"] <= b for a, b in spans):
            continue
        shift = sum(b - a for a, b in spans if b <= w["start"])
        out.append({**w,
                    "start": round(w["start"] - shift, 3),
                    "end": round(w["end"] - shift, 3)})
    return out


def _keep_expr(spans: list[tuple[float, float]]) -> str:
    parts = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in spans)
    return f"not({parts})"


def apply(source: Path, spans: list[tuple[float, float]], out: Path, fps: int) -> Path:
    """Вирізає шматки з відео та звуку одним проходом ffmpeg."""
    spans = merge_spans(spans)
    if not spans:
        return source
    expr = _keep_expr(spans)
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", str(source),
        "-vf", f"select='{expr}',setpts=N/FRAME_RATE/TB",
        "-af", f"aselect='{expr}',asetpts=N/SR/TB",
        "-r", str(fps), "-fps_mode", "cfr",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"Різання впало:\n{res.stderr[-1500:]}")
    return out
