#!/bin/bash
# Монтажер Hlyboki Sensy — встановлення.
#
# Ставить усе, що потрібно для монтажу: оточення Python, розпізнавання мови,
# пошук обличчя, ffmpeg і рушій рендеру. Потім кладе іконку панелі на робочий стіл.
#
# Запуск:  ./install.sh
#
# Автор: Олена Дубицька — @hlyboki_sensy · hlyboki-sensy.com

set -e
cd "$(dirname "$0")"
PKG="$(pwd)"

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  ✓ %s\n' "$1"; }
warn() { printf '  ! %s\n' "$1"; }
die()  { printf '\n\033[31m%s\033[0m\n\n' "$1"; exit 1; }

say "Монтажер Hlyboki Sensy — встановлення"

# --- 1. Що вже є на компʼютері -----------------------------------------------

[ "$(uname)" = "Darwin" ] || die "Поки що працює лише на macOS: пошук обличчя
спирається на вбудований у систему Vision."

command -v python3 >/dev/null || die "Не знайдено python3.
Постав його з python.org або через Homebrew: brew install python"
ok "python3 — $(python3 --version 2>&1 | cut -d' ' -f2)"

command -v node >/dev/null || die "Не знайдено node.
Постав Node.js 18 або новіший: https://nodejs.org (кнопка LTS)"
NODE_MAJOR="$(node -v | sed 's/v\([0-9]*\).*/\1/')"
[ "$NODE_MAJOR" -ge 18 ] || die "Потрібен Node.js 18 або новіший, а стоїть $(node -v).
Онови з https://nodejs.org"
ok "node — $(node -v)"

# --- 2. Оточення Python ------------------------------------------------------

say "Оточення Python"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ok "створено .venv"
else
  ok ".venv уже є"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python3 -m pip install --upgrade pip --quiet

say "Розпізнавання мови, пошук обличчя, ffmpeg"
printf '  качаю (перший раз це кілька хвилин)…\n'
python3 -m pip install --quiet -r requirements.txt
ok "faster-whisper, pyobjc, ffmpeg"

# ffmpeg із пакета static-ffmpeg лежить у .venv/bin — робимо його видимим.
if ! command -v ffmpeg >/dev/null; then
  if [ -x ".venv/bin/ffmpeg" ]; then
    ok "ffmpeg беремо з оточення пакета"
  else
    warn "ffmpeg не знайдено в системі. Якщо монтаж падатиме — постав: brew install ffmpeg"
  fi
else
  ok "ffmpeg — $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3)"
fi

# --- 3. Рушій рендеру --------------------------------------------------------

say "Рушій рендеру (Remotion)"
printf '  качаю (це найдовший крок, кілька хвилин)…\n'
( cd engine && npm install --silent --no-fund --no-audit )
ok "готово"

# --- 4. Папки ----------------------------------------------------------------

python3 -c "
import sys; sys.path.insert(0, 'engine/bin')
import _paths; _paths.ensure_dirs()
print('  ✓ папки на місці')
"

# --- 5. Іконка панелі на робочому столі --------------------------------------

say "Панель «Завдання до відео»"
APP="$HOME/Desktop/Завдання до відео.app"
rm -rf "$APP"
# Обовʼязково osacompile: бандл, у якому виконуваний файл — це shell-скрипт,
# macOS відкривати відмовляється (помилка -10669). І шлях має бути абсолютним:
# у середовищі `do shell script` змінна $HOME порожня.
osacompile -o "$APP" -e "do shell script \"nohup '$PKG/.venv/bin/python3' '$PKG/panel/server.py' >/dev/null 2>&1 &\"" >/dev/null
[ -f panel/icon.icns ] && cp panel/icon.icns "$APP/Contents/Resources/applet.icns"
touch "$APP"
ok "іконка на робочому столі"

# --- Готово ------------------------------------------------------------------

cat <<'EOF'

────────────────────────────────────────────────────────
  Готово.

  Далі:
    1. Кинь відео у папку inbox/ (або натисни «Додати відео» в панелі)
    2. Відкрий на робочому столі «Завдання до відео», заповни форму
    3. Відкрий цю папку в Claude Code і скажи: «завдання готове»

  Перший монтаж буде повільнішим: модель розпізнавання
  докачується один раз, далі працює миттєво.

  Монтажер Hlyboki Sensy — Олена Дубицька
  instagram.com/hlyboki_sensy · hlyboki-sensy.com
────────────────────────────────────────────────────────

EOF
