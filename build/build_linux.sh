#!/usr/bin/env bash
# 在 Linux 上打成 dist/drink_or_not 单文件可执行程序。
#
#   bash build/build_linux.sh
#
# 打完的二进制仍然要求桌面是 X11 或 XWayland(见 README 的「已知限制」)。

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

echo "==> 同步依赖"
uv sync

echo "==> 生成素材(已存在则跳过)"
[ -f assets/manifest.json ] || uv run python script/prepare_assets.py
[ -f assets/frames/idle_00.png ] || uv run python script/generate_frames.py

echo "==> PyInstaller 打包"
uv run --with pyinstaller pyinstaller "$ROOT/build/drink_or_not.spec" \
    --noconfirm --clean --workpath "$ROOT/build/.work" --distpath "$ROOT/dist"

echo
echo "产物: $ROOT/dist/drink_or_not"
echo "自测: $ROOT/dist/drink_or_not --debug-idle"
