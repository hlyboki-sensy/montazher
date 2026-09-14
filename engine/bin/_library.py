"""Каталог вставок — зіставляє те, що лежить у бібліотеці, з тим, що сказано.

Файл із каталогу зʼявляється там, де в записі звучить одне з його ключових слів.
Слова пишуться коренем, без закінчення: «фінанс» ловить і «фінансовими», і
«фінанси», бо українська змінює хвіст слова, а не початок.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _paths  # noqa: E402

LIBRARY = _paths.LIBRARY
CATALOG = "catalog.json"

# Скільки вставок максимум на ролик і скільки секунд між ними — щоб екран не
# перетворився на ярмарок.
MAX_INSERTS = 5
MIN_GAP_SEC = 6.0
DEFAULT_DUR = 3.4

TRIM = " ,.!?…:;—-«»\"'()"


def load(library: Path | None = None) -> dict:
    lib = library or LIBRARY
    path = lib / CATALOG
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    # показуємо лише те, що справді лежить у папці
    return {k: v for k, v in data.items() if (lib / k).is_file()}


def save(catalog: dict, library: Path | None = None) -> None:
    lib = library or LIBRARY
    lib.mkdir(parents=True, exist_ok=True)
    (lib / CATALOG).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def sync(library: Path | None = None) -> dict:
    """Додає у каталог файли, які просто поклали в папку повз панель."""
    lib = library or LIBRARY
    if not lib.exists():
        return {}
    try:
        raw = json.loads((lib / CATALOG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    changed = False
    for p in sorted(lib.iterdir()):
        if not p.is_file() or p.name == CATALOG or p.name.startswith("."):
            continue
        if p.suffix.lower() not in {".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov"}:
            continue
        if p.name not in raw:
            # Імʼя файлу — перша здогадка про ключові слова.
            guess = [w for w in p.stem.lower().replace("_", "-").split("-") if len(w) > 2]
            raw[p.name] = {"keywords": guess, "kind": "image", "credit": ""}
            changed = True
    if changed:
        save(raw, lib)
    return {k: v for k, v in raw.items() if (lib / k).is_file()}


def match(words: list[dict], catalog: dict, hold: float = DEFAULT_DUR) -> list[dict]:
    """Знаходить у розшифровці місця, де спрацьовує кожен файл каталогу."""
    hits = []
    for name, meta in catalog.items():
        keys = [k.strip().lower() for k in meta.get("keywords", []) if k.strip()]
        if not keys:
            continue
        for w in words:
            bare = w["word"].strip(TRIM).lower()
            if not bare:
                continue
            if any(bare.startswith(k) for k in keys):
                hits.append({
                    "name": name,
                    "at": w["start"],
                    "word": bare,
                    "kind": meta.get("kind", "image"),
                    "credit": meta.get("credit", ""),
                })
                break          # один файл — одна поява, щоб не повторювався
    hits.sort(key=lambda h: h["at"])

    chosen: list[dict] = []
    for h in hits:
        if len(chosen) >= MAX_INSERTS:
            break
        if chosen and h["at"] - chosen[-1]["at"] < MIN_GAP_SEC:
            continue           # надто щільно до попередньої
        chosen.append(h)

    return [{
        "fromSec": round(max(h["at"] - 0.25, 0), 2),
        "durSec": hold,
        "kind": h["kind"],
        "src": f"library/{h['name']}",
        "credit": h["credit"] or None,
        "_word": h["word"],
    } for h in chosen]


def stage(inserts: list[dict], public_dir: Path, library: Path | None = None) -> None:
    """Копіює вибрані файли туди, звідки їх бачить рушій рендеру."""
    lib = library or LIBRARY
    dest = public_dir / "library"
    dest.mkdir(parents=True, exist_ok=True)
    for ins in inserts:
        name = Path(ins["src"]).name
        src = lib / name
        if src.is_file():
            shutil.copy2(src, dest / name)
