#!/usr/bin/env bash
# 在 macOS 上打成 dist/drink_or_not(可再套 .app 外壳)。
#
#   bash build/build_macos.sh
#
# 注意:macOS 上 Qt.Tool 是 NSPanel,应用失活时会被系统自动隐藏,需要把
# pet_window.PetWindow 的窗口 flags 从 Qt.Tool 换成 Qt.Window 并调整窗口层级。
# 详见 README「已知限制」——在改之前,这个平台的拖动定位行为是降级的。

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
