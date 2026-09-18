#!/usr/bin/env bash
# 在 macOS 上打成 dist/drink_or_not。
#
#   bash build/build_macos.sh
#
# 注意:产物是**裸 Mach-O 可执行文件,不是 .app**。没有 Info.plist 就意味着激活策略、
# Dock 表现、托盘行为都可能和一个正经 .app 不一样 —— 套 .app 外壳(BUNDLE/Info.plist/
# .icns)目前还没做,判断行为时要把这一点算进去。
#
# 窗口失活被系统隐藏这个问题靠 pet_window.apply_window_flags() 里的
# WA_MacAlwaysShowToolWindow 解决,**不要**把 Qt.Tool 换成 Qt.Window(普通 NSWindow 拿不到
# NSWindowStyleMaskNonactivatingPanel,只会更糟)。详见 README「已知限制」第 5 条。
#
# 打完先跑一遍自检,它会打印一份只能肉眼确认的清单:
#   uv run python script/check_env.py --hold

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
