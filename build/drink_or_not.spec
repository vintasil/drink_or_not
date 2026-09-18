# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置,三个平台共用。

    uv run --with pyinstaller pyinstaller build/drink_or_not.spec --noconfirm --clean

产物在 dist/。assets/ 整个目录塞进包里,resources.assets_dir() 会从 _MEIPASS 读它。
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = 本文件所在目录(build/)

a = Analysis(
    # 不能直接用 src/drink_or_not/__main__.py:见 build/entry.py 的说明
    [str(ROOT / "build" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=[
        "PyQt5.QtDBus",  # 空闲检测走 DBus,不在 QtCore/QtGui 的默认收集范围内
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "numpy"],  # PIL 是运行时依赖(导入形象要抠图),不能再排掉
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
