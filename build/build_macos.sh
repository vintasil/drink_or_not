#!/usr/bin/env bash
# 在 macOS 上打成 dist/drink_or_not.app。
#
#   bash build/build_macos.sh
#
# 产物是**自包含的 .app 外壳**:解释器、Qt 库、assets 全在里面,拷给别人双击就能开,
# 对方不需要联网、不需要装 uv、不需要开终端。这是它和 build_macos_uvbox.sh 的根本区别
# ——uvbox 那个是薄启动器,首次运行要联网下载。
#
# 窗口失活被系统隐藏这个问题靠 pet_window.apply_window_flags() 里的
# WA_MacAlwaysShowToolWindow 解决,**不要**把 Qt.Tool 换成 Qt.Window(普通 NSWindow 拿不到
# NSWindowStyleMaskNonactivatingPanel,只会更糟)。详见 README「已知限制」第 5 条。
#
# 打完先自测,它会逐项判定 + 打印一份只能肉眼确认的清单:
#   ./dist/drink_or_not.app/Contents/MacOS/drink_or_not --self-check --hold
# 跑 .app 内部那个可执行文件是为了拿到终端输出;macOS 仍会按路径认出它属于这个 bundle。
# 想验"双击"那条路:  open dist/drink_or_not.app
#
# 图标(Dock / Finder 里那个)来自 script/make_icon.py,源头是 pic/cat/magic_cat.png。
# 想换图就覆盖那张原图、想改形状就改脚本里的尺寸常量;改完先看 build/icon.png 再打包。
#
# 构建报 codesign / xcrun 相关错 -> 先装 Command Line Tools 再重来:
#   xcode-select --install

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

echo "==> 同步依赖"
uv sync

echo "==> 生成素材(已存在则跳过)"
[ -f assets/manifest.json ] || uv run python script/prepare_assets.py
[ -f assets/frames/idle_00.png ] || uv run python script/generate_frames.py

echo "==> 生成图标(.icns 是派生文件,不进仓库,每次现做)"
uv run python script/make_icon.py

echo "==> PyInstaller 打包"
uv run --with pyinstaller pyinstaller "$ROOT/build/drink_or_not.spec" \
    --noconfirm --clean --workpath "$ROOT/build/.work" --distpath "$ROOT/dist"

echo
echo "产物: $ROOT/dist/drink_or_not.app"
echo "自测: $ROOT/dist/drink_or_not.app/Contents/MacOS/drink_or_not --self-check --hold"
echo
echo "发给别人之前压成包(直接传 .app 目录会丢可执行权限和内部符号链接):"
echo "  cd $ROOT/dist && zip -qry drink_or_not-macos-\$(uname -m).zip drink_or_not.app"
