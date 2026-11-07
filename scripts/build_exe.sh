#!/usr/bin/env bash
# 在 Linux/macOS/MSYS 下构建单文件可执行程序。
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python}"
"$PYTHON" -m pip install --upgrade pyinstaller
"$PYTHON" -m PyInstaller --noconfirm --clean --distpath dist --workpath build labpbr2bedrock.spec
echo "完成：dist/labpbr2bedrock"
