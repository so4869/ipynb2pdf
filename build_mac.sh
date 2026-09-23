#!/usr/bin/env bash
# ipynb2pdf macOS/Linux build script -> dist/ipynb2pdf
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt pyinstaller
python tools/make_fontlist.py
rm -rf build dist
pyinstaller --clean --noconfirm ipynb2pdf.spec
echo "===== build done: dist/ipynb2pdf ====="
