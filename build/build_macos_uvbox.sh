#!/usr/bin/env bash
# 在 Linux/Ubuntu 上交叉产出 macOS 可执行文件(uvbox 路线)。
#
#   bash build/build_macos_uvbox.sh            # 只为 macOS 两个架构打
#   bash build/build_macos_uvbox.sh --linux    # 顺带打个 Linux 变体,好在 Ubuntu 上先跑一遍
#
# 产物:dist/drink-or-not-{x86_64,aarch64}-apple-darwin.tar.gz
#
# 这条路线和 build_macos.sh(PyInstaller)**不是一回事**,别混:
#
#   * PyInstaller 不能交叉编译,只能在 Mac 上打;打出来是自包含的裸 Mach-O。
#   * uvbox 是个 Go 写的启动器,内嵌了一份 uv 和**本项目的 wheel**(含 assets,由
#     pyproject.toml 的 force-include 带进去)。产物一样是裸可执行文件,没有 .app。
#     代价:**目标机首次运行时**要把 uv、CPython、PyQt5/Pillow 下载下来装好,所以第一
#     次跑必须联网,而且要等一两分钟。之后按盒子缓存复用。
#
# 目标机(Sequoia 15.1.1)上的验证:
#     tar xzf dist/drink-or-not-aarch64-apple-darwin.tar.gz -C /tmp/xy
#     /tmp/xy/drink-or-not --self-check --hold      # 逐项自检 + 肉眼核对清单
#
# **两个坑,踩过一次了:**
#   1. 盒子缓存目录名是 <name>-<hash>,hash 只跟 build/uvbox.toml 和平台有关。改了 wheel
#      但配置没动 -> hash 不变 -> 目标机复用旧盒子,跑的还是老代码。要验新产物,先删掉
#      ~/.local/share/uvbox/drink-or-not-* 再跑。
#   2. 机器时钟错了会让 uv 的缓存/HTTP 校验出怪问题。产物行为反常时先对一下时间。

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

ALSO_LINUX=0
[ "${1:-}" = "--linux" ] && ALSO_LINUX=1

echo "==> 生成素材(已存在则跳过)"
[ -f assets/manifest.json ] || uv run python script/prepare_assets.py
[ -f assets/frames/idle_00.png ] || uv run python script/generate_frames.py

echo "==> 构建 wheel(assets 由 pyproject.toml 的 force-include 打进包内)"
rm -rf "$ROOT/build/.wheelhouse"
uv build --wheel --out-dir "$ROOT/build/.wheelhouse"

WHEEL="$(ls "$ROOT"/build/.wheelhouse/*.whl)"
echo "    $WHEEL"

TARGETS=(--darwin --amd --arm)
[ "$ALSO_LINUX" = 1 ] && TARGETS+=(--linux)

echo "==> uvbox 交叉打包"
uvx uvbox wheel "$WHEEL" \
    -c "$ROOT/build/uvbox.toml" \
    "${TARGETS[@]}" \
    -o "$ROOT/dist"

echo
echo "产物:"
ls -1 "$ROOT"/dist/*.tar.gz
if [ "$ALSO_LINUX" = 1 ]; then
    cat <<'EOF'

本机可先验的那一份(bash 里跑,它才看得到 DISPLAY):
    rm -rf /tmp/uvrun && mkdir /tmp/uvrun
    tar xzf dist/drink-or-not-x86_64-unknown-linux-gnu.tar.gz -C /tmp/uvrun
    /tmp/uvrun/drink-or-not --debug-idle      # 或 --self-check

注意:uvbox 那条路在 Ubuntu 上只能证明"装得起来、assets 找得到、逻辑不变",证明不了
任何 macOS 特有的行为 —— 那些仍然只能上真机,照 --self-check 末尾的清单过一遍。
EOF
fi
