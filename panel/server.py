#!/usr/bin/env python3
"""Панель завдань до відео — маленький локальний сервер.

Показує форму в браузері, дає вибрати файли рідним діалогом macOS, складає їх
у inbox/ і зберігає заповнене завдання у вигляді .md, який читає Клод.

Файли не завантажуються через браузер: замість цього відкривається звичайне
вікно вибору файлів, а сервер копіює обране. Так відео на сто мегабайтів не
доводиться ганяти через HTTP.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Шляхи бере пакет — панель нічого не знає про те, де він лежить.
sys.path.insert(0, str(HERE.parent / "engine" / "bin"))
import _paths  # noqa: E402

INBOX = _paths.INBOX
ASSETS = _paths.ASSETS
LIBRARY = _paths.LIBRARY
CATALOG = LIBRARY / "catalog.json"
LIB_EXT = {".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov"}

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mp3", ".wav", ".m4a", ".aac"}
ASSET_EXT = VIDEO_EXT | {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".pdf"}

# Пів робочого дня. Тридцяти хвилин не вистачало: поки переглядаєш ролики
# чи відповідаєш на дзвінок, панель встигала загаснути, і сторінка в браузері
# ставала мертвою без жодного пояснення.
IDLE_MINUTES = 240
_last_seen = time.time()

# Візитівка панелі — щоб не переплутати себе з чужим сервером на порту.
MARKER = "montazher-panel"


def listing(folder: Path, allowed: set[str]) -> list[str]:
    if not folder.exists():
        return []
    return sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in allowed and not p.name.startswith(".")
    )


def choose_files(prompt: str, start: Path | None = None) -> list[Path]:
    """Рідний діалог вибору файлів macOS.

    Відкривається одразу в нашій теці, щоб не шукати її щоразу заново; якщо
    теки ще немає —система покаже типову.
    """
    where = ""
    if start and start.exists():
        where = f' default location POSIX file "{start}"'
    script = f'''
    tell application "System Events" to activate
    set picked to choose file with prompt "{prompt}"{where} with multiple selections allowed
    set out to ""
    repeat with f in picked
        set out to out & POSIX path of f & linefeed
    end repeat
    return out
    '''
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:          # користувач натиснув «Скасувати»
        return []
    return [Path(line) for line in res.stdout.splitlines() if line.strip()]


def adopt(paths: list[Path], folder: Path, allowed: set[str]) -> list[str]:
    """Копіює вибрані файли до нас, не затираючи однойменні."""
    folder.mkdir(parents=True, exist_ok=True)
    taken = []
    for src in paths:
        if src.suffix.lower() not in allowed or not src.is_file():
            continue
        dest = folder / src.name
        n = 2
        while dest.exists() and dest.stat().st_size != src.stat().st_size:
            dest = folder / f"{src.stem}-{n}{src.suffix}"
            n += 1
        if not dest.exists():
            shutil.copy2(src, dest)
        taken.append(dest.name)
    return taken


def catalog_read() -> dict:
    """Каталог вставок + підхоплення файлів, покладених у папку повз панель."""
    LIBRARY.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    changed = False
    for p in sorted(LIBRARY.iterdir()):
        if not p.is_file() or p.name == CATALOG.name or p.name.startswith("."):
            continue
        if p.suffix.lower() not in LIB_EXT:
            continue
        if p.name not in data:
            guess = [w for w in p.stem.lower().replace("_", "-").split("-") if len(w) > 2]
            data[p.name] = {"keywords": guess, "kind": "image", "credit": ""}
            changed = True
    data = {k: v for k, v in data.items() if (LIBRARY / k).is_file()}
    if changed:
        catalog_write(data)
    return data


def catalog_write(data: dict) -> None:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --- Складання тексту завдання ------------------------------------------------

def section(title: str, body: str, empty: str) -> str:
    body = (body or "").strip()
    return f"## {title}\n\n{body if body else empty}\n\n"


def render(d: dict) -> str:
    videos = d.get("videos") or []
    assets = d.get("assets") or []

    out = "# Завдання до відео\n\n"
    if len(videos) == 1:
        out += f"**Файл:** `{videos[0]}`  \n"
    else:
        out += f"**Файли ({len(videos)}), у цьому порядку:**\n\n"
        for i, v in enumerate(videos, 1):
            out += f"{i}. `{v}`\n"
        out += "\n"
    looks = {
        "podcast": "подкастовий (дрібне біле + великі ключові фрази каліграфією)",
        "calligraphy": "каліграфія (Great Vibes кольором акценту + білий капс)",
        "classic": "класичний (дідонівський серіф: курсив + капс)",
        "editorial": "редакторський (щіточний рукопис + капс + кольоровий акцент)",
        "quiet": "тихий (одне слово в кадрі, біле, малими)",
        "bold": "капс-блок (білий капс + кольорове ключове слово)",
    }
    look = d.get("look", "podcast")
    accent = (d.get("accentColor") or "").upper()
    names = {"#660033": "сливовий — акцент пакета", "#FFFFFF": "білий — без підсвітки",
             "#C8A96A": "приглушене золото", "#FF8A7A": "теплий кораловий",
             "#8FD8C8": "мʼятний", "#4FA6FF": "синій"}
    out += (
        f"**Бренд:** {d.get('brand')}  \n"
        f"**Куди піде:** {d.get('dest')}  \n"
        f"**Стиль субтитрів:** `{look}` — {looks.get(look, look)}  \n"
    )
    edges = {"halo": "темний ореол і тінь", "shadow": "лише мʼяка тінь",
             "none": "нічого — чистий текст"}
    edge = d.get("edge", "halo")
    out += f"**Під літерами:** `{edge}` — {edges.get(edge, edge)}  \n"
    if accent:
        out += f"**Колір у субтитрах:** `{accent}`" + (
            f" — {names[accent]}" if accent in names else "") + "  \n"
    out += "**Формат:** вертикаль 9:16\n\n"



    out += section("Про що це", d.get("about"), "_не вказано — на твій розсуд_")

    out += "## Що зробити\n\n"
    for t in d.get("tasks", []):
        mark = "x" if t["on"] else " "
        ready = "✅" if t["ready"] else "🔧"
        label = t["label"]
        if t.get("value"):
            label += f" — `{t['value']}{t.get('suffix', '')}`"
        out += f"- [{mark}] {ready} {label}\n"
    out += "\n"

    if len(videos) > 1:
        out += "## Монтаж\n\n"
        out += f"**Характер:** {d.get('pace', 'не вказано')}\n\n"
        out += f"**Переходи:** {d.get('transition', 'не вказано')}\n\n"
        notes = (d.get("montage") or "").strip()
        out += f"{notes}\n\n" if notes else ""

    out += "## Вставки\n\n"
    if d.get("useLibrary"):
        out += "- [x] ✅ Брати з каталогу за збігом ключових слів\n"
    if d.get("autoStock"):
        where = {
            "draw": "намалювати в стилі бренду",
            "open": "відкриті бібліотеки (Openverse, Wikimedia Commons)",
            "web": "будь-де в інтернеті — показати кандидатів на вибір",
        }.get(d.get("source", "draw"), "на твій розсуд")
        out += f"- [x] 🔧 Знайти матеріал самостійно — **{where}**\n\n"
    if assets:
        out += "Мої файли в `inbox/assets/`:\n\n"
        for a in assets:
            out += f"- `{a}`\n"
        out += "\n"
    plan = (d.get("inserts") or "").strip()
    out += f"{plan}\n\n" if plan else ""
    if not assets and not plan and not d.get("autoStock") and not d.get("useLibrary"):
        out += "_вставок не треба_\n\n"

    out += section("Чого не робити", d.get("dont"), "_нема окремих застережень_")

    out += "## Особливе\n\n"
    for title, key, empty in (
        ("Імена й терміни — написати саме так", "terms", "_нема_"),
        ("Що підсвітити акцентом у субтитрах", "accents", "_на твій розсуд_"),
        ("Що прибрати з тексту", "cut", "_нема_"),
    ):
        value = (d.get(key) or "").strip()
        out += f"**{title}**\n\n{value if value else empty}\n\n"
    return out.rstrip() + "\n"


# --- Сервер -------------------------------------------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        # Панель живе на localhost і міняється часто: варто мені перезняти
        # превʼю стилів, як Chrome однаково показував старі з кешу.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def handle_one_request(self):
        global _last_seen
        _last_seen = time.time()
        super().handle_one_request()

    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/whoami":
            # Візитівка панелі: за нею застосунок відрізняє нас від чужого
            # сервера, який випадково зайняв той самий порт.
            body = MARKER.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/":
            self.path = "/panel.html"
        elif self.path == "/reveal":
            # Показати теку у Finder — звідти зручно прибрати зайві файли.
            subprocess.run(["open", str(INBOX)], capture_output=True)
            return self._json({"ok": True})
        elif self.path == "/videos":
            return self._json(listing(INBOX, VIDEO_EXT))
        elif self.path == "/assets":
            return self._json(listing(ASSETS, ASSET_EXT))
        elif self.path == "/library":
            data = catalog_read()
            return self._json([
                {"name": k, "keywords": v.get("keywords", []),
                 "credit": v.get("credit", "")}
                for k, v in sorted(data.items())
            ])
        return super().do_GET()

    def do_POST(self):
        try:
            if self.path == "/library/add":
                picked = choose_files("Оберіть файли для каталогу вставок")
                added = adopt(picked, LIBRARY, LIB_EXT)
                catalog_read()          # одразу заводимо їх у каталог
                return self._json({"ok": True, "added": added})

            if self.path == "/library/keywords":
                data = self._body()
                cat = catalog_read()
                name = data.get("name")
                if name not in cat:
                    return self._json({"ok": False, "error": "такого файлу в каталозі немає"}, 400)
                words = [w.strip() for w in (data.get("keywords") or "").split(",") if w.strip()]
                cat[name]["keywords"] = words
                catalog_write(cat)
                return self._json({"ok": True, "keywords": words})

            if self.path == "/library/remove":
                data = self._body()
                cat = catalog_read()
                name = data.get("name")
                if name in cat:
                    cat.pop(name)
                    catalog_write(cat)
                    f = LIBRARY / name
                    if f.is_file():
                        f.unlink()
                return self._json({"ok": True})

            if self.path == "/pick":
                data = self._body()
                is_asset = data.get("kind") == "asset"
                prompt = "Оберіть вставки — картинки або відео" if is_asset else "Оберіть відео"
                folder = ASSETS if is_asset else INBOX
                picked = choose_files(prompt, folder)
                allowed = ASSET_EXT if is_asset else VIDEO_EXT
                return self._json({"ok": True, "added": adopt(picked, folder, allowed)})

            if self.path == "/save":
                data = self._body()
                videos = data.get("videos") or []
                if not videos:
                    return self._json({"ok": False, "error": "не обрано жодного відео"}, 400)
                name = (data.get("name") or "").strip() or Path(videos[0]).stem
                safe = "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "завдання"
                target = INBOX / f"{safe}.md"
                target.write_text(render(data), encoding="utf-8")
                return self._json({"ok": True, "name": target.name})
        except (ValueError, UnicodeDecodeError):
            return self._json({"ok": False, "error": "не зміг прочитати форму"}, 400)
        except OSError as exc:
            return self._json({"ok": False, "error": f"не зміг записати: {exc}"}, 500)
        return self._json({"ok": False, "error": "невідомий запит"}, 404)


def port_answers(port: int) -> bool:
    """Чи хтось справді відповідає на цьому порту."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def free_port(preferred: int = 8230) -> int:
    """Перший порт, на якому ніхто не відповідає.

    Свідомо перевіряємо звʼязком, а не спробою зайняти: після зупинки сервера
    порт ще деякий час не дає себе зайняти, хоч на ньому вже нікого немає. Через
    це панель тікала на випадковий порт, а застосунок шукав її на своєму.
    """
    for port in range(preferred, preferred + 40):
        if not port_answers(port):
            return port
    return 0


def panel_answers(port: int) -> bool:
    """Чи це НАША панель, а не чужий сервер на тому самому порту.

    Раніше перевіряли тільки «хтось відповідає» — і коли порт займав інший
    локальний сервер, застосунок слухняно відкривав чужу сторінку. Тепер
    питаємо в того, хто відповів, хто він такий.
    """
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/whoami", timeout=0.6
        ) as res:
            return res.read(64).decode("utf-8", "replace").strip() == MARKER
    except Exception:
        return False


def find_panel(preferred: int = 8230, span: int = 10) -> int | None:
    """Порт, на якому вже живе наша панель, якщо вона взагалі жива."""
    for port in range(preferred, preferred + span):
        if port_answers(port) and panel_answers(port):
            return port
    return None


def watchdog() -> None:
    while True:
        time.sleep(60)
        if time.time() - _last_seen > IDLE_MINUTES * 60:
            os._exit(0)


def main() -> None:
    running = find_panel()
    if running:
        webbrowser.open(f"http://127.0.0.1:{running}/")
        return
    port = free_port()
    # Обовʼязково потоковий. Chrome відкриває «запасні» зʼєднання наперед і
    # нічого ними не шле; однопотоковий сервер завмирав на такому сокеті й
    # переставав відповідати всім іншим — зокрема на /whoami.
    Server = socketserver.ThreadingTCPServer
    Server.allow_reuse_address = True
    Server.allow_reuse_port = True
    Server.daemon_threads = True
    with Server(("127.0.0.1", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}/"
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        threading.Thread(target=watchdog, daemon=True).start()
        print(f"Панель завдань: {url}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
