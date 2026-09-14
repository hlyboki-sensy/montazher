"""Наскільки світлий кадр саме там, де стоятиме напис.

Один і той самий колір не може читатися і на снігу, і на нічному кадрі. Тому
перед розкладкою ми міряємо яскравість тієї смуги, куди ляже репліка, і кажемо
композиції, якою парою кольорів писати: світлою по темному чи темною по світлому.

Рахує ffmpeg (фільтр signalstats), тож жодних додаткових бібліотек не треба.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# YAVG приходить у шкалі 0–255. Нижче цього порога вважаємо кадр темним.
# 118 — не середина шкали навмисно: білий текст із темним ореолом пробачає
# трохи світліше тло, а темний текст на темному не рятує вже нічого.
DARK_BELOW = 118

_YAVG = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.]+)")


def _yavg(video: Path, at: float, box: dict | None) -> float | None:
    """Середня яскравість кадру (або його ділянки) у момент `at`."""
    chain = []
    if box:
        # Частки кадру → пікселі. Мінімум 8 пікселів, інакше crop падає.
        chain.append(
            "crop="
            f"max(8\\,iw*{box['w']:.4f}):max(8\\,ih*{box['h']:.4f}):"
            f"iw*{max(box['x'], 0):.4f}:ih*{max(box['y'], 0):.4f}"
        )
    # file=- ОБОВʼЯЗКОВО: без нього metadata пише замір у лог на рівні info,
    # який глушиться -v error, і функція мовчки повертає None.
    chain += ["signalstats", "metadata=print:key=lavfi.signalstats.YAVG:file=-"]
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(at, 0):.2f}", "-i", str(video),
         "-frames:v", "1", "-vf", ",".join(chain), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    found = _YAVG.search(proc.stdout) or _YAVG.search(proc.stderr)
    return float(found.group(1)) if found else None


def is_dark(video: Path, at: float, box: dict | None) -> bool | None:
    """True — під написом темно, False — світло, None — виміряти не вдалося.

    None буває, коли джерело взагалі без відео (голосовий файл) — тоді рішення
    лишається за композицією, а вона типово вважає кадр темним.
    """
    y = _yavg(video, at, box)
    if y is None:
        return None
    return y < DARK_BELOW


def has_video(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return "video" in proc.stdout
