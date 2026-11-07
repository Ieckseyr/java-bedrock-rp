#!/usr/bin/env bash
# 重建本仓库随附的 rotrBLOCKS 三套基岩包（使用文件夹工作流）。
#
# 用法：
#   bash scripts/build_packs.sh
#   JOBS=4 bash scripts/build_packs.sh
set -euo pipefail

cd "$(dirname "$0")/.."

JOBS="${JOBS:-8}"
PYTHON="${PYTHON:-python}"
SRC_DIR="材质包/Java"
GROUP="input/rotrBLOCKS_512x"
CONFIG="build.config.json"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "未找到 $SRC_DIR；这个脚本假设随附的 Java 材质包还在仓库里。" >&2
  exit 1
fi

mkdir -p "$GROUP"

link_or_copy() {
  local src="$1" dst="$2"
  if [[ -f "$dst" ]]; then
    return
  fi
  ln "$src" "$dst" 2>/dev/null || cp "$src" "$dst"
}

link_or_copy "$SRC_DIR/rotrBLOCKS BASE V73 1.21.4-1.13 512x.zip"      "$GROUP/01_BASE.zip"
link_or_copy "$SRC_DIR/rotrBLOCKS DESIGN V73 1.21.4-1.13 512x.zip"    "$GROUP/02_DESIGN.zip"
link_or_copy "$SRC_DIR/rotrBLOCKS DUNGEONS V73 1.21.4-1.13 512x.zip"  "$GROUP/03_DUNGEONS.zip"
link_or_copy "$SRC_DIR/rotrBLOCKS FLORA V73 1.21.4-1.13 512x.zip"     "$GROUP/04_FLORA.zip"
link_or_copy "$SRC_DIR/rotrBLOCKS Emiores 1.20.1-1.13 256-512x.zip"   "$GROUP/05_Emiores.zip"

cat > "$CONFIG" <<JSON
{
  "version": 1,
  "input_dir": "input",
  "output_dir": "output",
  "mode": "heightmap",
  "modes": [],
  "preset": "split",
  "jobs": $JOBS,
  "overwrite": false,
  "verify": true,
  "report": true,
  "name_suffix": "_bedrock",
  "include_mode_in_name": false,
  "vibrant_visuals": false,
  "conversion": {
    "mixed_include_heightmap_files": true
  },
  "targets": []
}
JSON

PYTHONPATH=src "$PYTHON" -m labpbr2bedrock run --config "$CONFIG" --force

echo
echo "完成。产物："
ls -lh output/*.mcpack
