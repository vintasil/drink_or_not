#!/usr/bin/env bash
# 在 Linux 上借 Wine 打出 dist/windows/drink_or_not.exe。
#
#   bash build/build_windows_on_wine.sh
#
# 手边没有 Windows 机器时的权宜之计,**不是**官方支持路径。产物能不能在真机上跑要
# 自己验:Wine 提供的系统 DLL 和真 Windows 有出入,Qt 尤其吃这套。有 Windows 机器
# 的话,在那边跑 build\build_windows.bat 更靠谱。
#
# 需要一个装好 Windows 版 Python + PyInstaller + PyQt5 的 Wine prefix。没现成的就:
#
#   export WINEPREFIX=~/.wine-pyinstaller
#   wineboot -i
#   # 装 Windows 版 Python(3.8+,勾 Add to PATH),然后
#   wine py -m pip install PyQt5==5.15.11 pyinstaller
#
# 可用环境变量覆盖:WINEPREFIX(默认 ~/.wine-pyinstaller)、WIN_PYTHON(python.exe 路径)。

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-pyinstaller}"
# 不设的话 Wine 会往 stderr 灌一堆 fixme/err,把 PyInstaller 自己的输出淹掉
export WINEDEBUG="${WINEDEBUG:--all}"

if [ ! -d "$WINEPREFIX" ]; then
    echo "找不到 Wine prefix: $WINEPREFIX" >&2
    echo "先按脚本头部的说明建一个,或 export WINEPREFIX 指到已有的。" >&2
    exit 1
fi
if ! command -v wine >/dev/null; then
    echo "没装 wine。Ubuntu/Debian:sudo apt install wine64 wine32:i386" >&2
    exit 1
fi

# --- 找 Windows 版 python.exe ---
find_python() {
    if [ -n "${WIN_PYTHON:-}" ]; then
        [ -f "$WIN_PYTHON" ] || { echo "WIN_PYTHON 指向的文件不存在: $WIN_PYTHON" >&2; exit 1; }
        printf '%s\n' "$WIN_PYTHON"
        return
    fi
    # 官方安装器默认落在 用户 AppData 或 C:\PythonXY;C:\ 根下的 python.exe
    # (py -m venv 之类)也认
    local found
    found=$(find "$WINEPREFIX/drive_c" -maxdepth 9 -iname 'python.exe' \
                -not -path '*/Lib/*' -not -path '*/Scripts/*' 2>/dev/null | head -1)
    if [ -z "$found" ]; then
        echo "prefix 里找不到 python.exe。先在里面装一个 Windows 版 Python:" >&2
        echo "  WINEPREFIX=$WINEPREFIX wine <python-3.x-installer>.exe" >&2
        exit 1
    fi
    printf '%s\n' "$found"
}

PY_UNIX="$(find_python)"
PY_WIN="$(winepath -w "$PY_UNIX")"

# --- 确认 prefix 里依赖齐全 ---
echo "==> Wine prefix: $WINEPREFIX"
echo "    Python     : $PY_WIN"
if ! PYCHECK=$(wine "$PY_WIN" -c "import PyQt5, PyInstaller" 2>&1); then
    printf '%s\n' "$PYCHECK" >&2
    if printf '%s' "$PYCHECK" | grep -q init_sys_streams; then
        # Wine 9 + Windows CPython 的已知毛病:stdout 既不是终端也不是管道时(重定向进文件、
        # 被 CI/脚本捕获),Python 说"无效的句柄"然后直接死,和依赖一点关系没有。
        echo >&2
        echo "这不是缺依赖,是 Wine 起不了 Python 的标准流 —— 上面那句 WinError 6 是症状。" >&2
        echo "换个普通终端重跑,或者让 stdout 走管道:" >&2
        echo "  bash build/build_windows_on_wine.sh 2>&1 | cat" >&2
    else
        echo >&2
        echo "这个 Python 里缺 PyQt5 或 PyInstaller,先装上:" >&2
        echo "  WINEPREFIX=$WINEPREFIX wine \"$PY_WIN\" -m pip install PyQt5==5.15.11 pyinstaller" >&2
    fi
    exit 1
fi

# --- 素材 ---
# 素材是用宿主 Python 生成后打进包里的,和打包平台无关,直接用 uv 跑就行
echo "==> 生成素材(已存在则跳过)"
[ -f assets/manifest.json ] || uv run python script/prepare_assets.py
[ -f assets/frames/idle_00.png ] || uv run python script/generate_frames.py

# --- 打包 ---
# 特意和 Linux 构建分开 workpath/distpath:PyInstaller 的 --noconfirm 是照着产物名删旧
# 文件,两个平台用到同一个 dist/ 时,它有可能把 dist/drink_or_not(Linux 那个)顺手删掉。
WORK="$(winepath -w "$ROOT/build/.work-win")"
DIST="$(winepath -w "$ROOT/dist/windows")"
SPEC="$(winepath -w "$ROOT/build/drink_or_not.spec")"

echo "==> PyInstaller 打包(Wine 里跑)"
wine "$PY_WIN" -m PyInstaller "$SPEC" \
    --noconfirm --clean --workpath "$WORK" --distpath "$DIST"

EXE="$ROOT/dist/windows/drink_or_not.exe"
if [ ! -f "$EXE" ]; then
    echo "打包没报错但没看到产物: $EXE" >&2
    exit 1
fi

echo
echo "产物: $EXE"
echo "自测: WINEPREFIX=$WINEPREFIX wine \"$EXE\" --debug-idle"
