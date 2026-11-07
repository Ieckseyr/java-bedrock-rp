#!/usr/bin/env bash
# 便携启动器（Linux / macOS / MSYS）
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[错误] 未找到 Python 3.10+，请先安装。" >&2
  exit 1
fi

exec "$PYTHON" run.py "$@"
