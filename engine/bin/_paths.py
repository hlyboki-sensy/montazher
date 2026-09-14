"""Шляхи пакета — одне місце, де вони описані.

Усе рахується від розташування самого файлу, тож пакет можна покласти
будь-куди: у Downloads, на зовнішній диск, у будь-яку папку з проєктами.
Нічого прописувати руками не треба.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# .../montazher/engine/bin/_paths.py → .../montazher
PKG = Path(__file__).resolve().parents[2]

ENGINE = PKG / "engine"
PUBLIC = ENGINE / "public"          # сюди лягає відео, яке бачить рендер
DATA = ENGINE / "src" / "data"      # сюди лягають готові props
INBOX = PKG / "inbox"               # звідси беремо вихідні записи
ASSETS = INBOX / "assets"           # свої картинки й кліпи для вставок
LIBRARY = PKG / "library"           # каталог вставок із ключовими словами
OUT = PKG / "out"                   # готові ролики

# Оточення Python, у якому стоять faster-whisper і pyobjc. Створює install.sh.
VENV_PYTHON = PKG / ".venv" / "bin" / "python3"


def _can_import(python: str, module: str) -> bool:
    probe = subprocess.run([python, "-c", f"import {module}"], capture_output=True)
    return probe.returncode == 0


def python_with(module: str) -> str:
    """Інтерпретатор, у якому є потрібний модуль.

    Спершу пробуємо той, яким запущено скрипт, далі — оточення пакета.
    Повертає шлях; якщо модуля немає ніде, все одно повертає поточний —
    хай викличник сам скаже людині зрозумілу помилку.
    """
    if _can_import(sys.executable, module):
        return sys.executable
    if VENV_PYTHON.exists() and _can_import(str(VENV_PYTHON), module):
        return str(VENV_PYTHON)
    return sys.executable


def ensure_dirs() -> None:
    for d in (PUBLIC, DATA, INBOX, ASSETS, LIBRARY, OUT):
        d.mkdir(parents=True, exist_ok=True)
