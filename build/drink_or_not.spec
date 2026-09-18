# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置,三个平台共用。

    uv run --with pyinstaller pyinstaller build/drink_or_not.spec --noconfirm --clean

产物在 dist/。assets/ 整个目录塞进包里,resources.assets_dir() 会从 _MEIPASS 读它。
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = 本文件所在目录(build/)

# 空闲检测在 Linux 上走 DBus,而 activity.py 里的 QtDBus 是延迟导入的,静态扫描看不见,
# 得手动列进来。Windows/macOS 的 provider 是 ctypes 调系统 API,用不到它。
# 这里按**执行本文件的解释器**所属平台判断 —— PyInstaller 用的就是目标平台的 Python,
# 在 Wine 里跑时 sys.platform 报 win32,正好落在实处。
HIDDEN = ["PyQt5.QtDBus"] if sys.platform.startswith("linux") else []

a = Analysis(
    [str(ROOT / "build" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PIL", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="drink_or_not",
    debug=False,
    strip=False,
    upx=False,  # UPX 压过的 Qt 库偶发加载失败,不值得省这点体积
    console=False,
    icon=None,
)
