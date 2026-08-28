#!/bin/bash
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  python3 launcher.py
else
  echo "Python 3 не найден. Установи его: https://www.python.org/downloads/"
  read -p "Нажми Enter, чтобы закрыть…"
fi
