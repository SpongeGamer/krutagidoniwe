#!/bin/bash
cd "$(dirname "$0")"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

# Python не нашёлся — пробуем поставить сами через Homebrew.
if [ -z "$PY" ]; then
  echo
  echo "  Python не найден. Попробую установить его сам."
  echo
  if command -v brew >/dev/null 2>&1; then
    brew install python
    command -v python3 >/dev/null 2>&1 && PY="python3"
  fi
fi

if [ -z "$PY" ]; then
  echo
  echo "  Автоматически не вышло. Поставь Python вручную:"
  echo "  1. Открой https://www.python.org/downloads/"
  echo "  2. Скачай и запусти установщик"
  echo "  3. Запусти этот файл снова"
  echo
  open "https://www.python.org/downloads/" 2>/dev/null
  read -p "Нажми Enter, чтобы закрыть…"
  exit 1
fi

echo "  Готовлю игру, первый запуск занимает полминуты…"
echo
"$PY" launcher.py
