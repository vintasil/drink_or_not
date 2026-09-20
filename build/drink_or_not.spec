# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置,三个平台共用。

    uv run --with pyinstaller pyinstaller build/drink_or_not.spec --noconfirm --clean

产物在 dist/。assets/ 整个目录塞进包里,resources.assets_dir() 会从 _MEIPASS 读它。
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = 本文件所在目录(build/)

a = Analysis(
    # 不能直接用 src/drink_or_not/__main__.py:见 build/entry.py 的说明
    [str(ROOT / "build" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=(
        # 空闲检测走 DBus,不在 QtCore/QtGui 的默认收集范围内
        ["PyQt5.QtDBus"]
        if sys.platform.startswith("linux")
        else []  # macOS/Windows 上没有 session bus,这条 provider 本来就用不到
    ),
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

if sys.platform == "darwin":
    # .app 外壳。裸 Mach-O 也能跑,但别人拿到只能开终端敲命令;套上 .app 才能双击启动、
    # 有图标、走 Launch Services。Windows/Linux 不产外壳,这个分支在那边完全不执行。
    app = BUNDLE(
        exe,
        name="drink_or_not.app",
        icon=None,  # 没做 .icns:要图标得在 Mac 上用 iconutil 生成,本次没做,用的是系统默认
        # 和 autostart 的 LaunchAgent Label 同一域名,免得同一个东西有两个身份
        bundle_identifier="com.drinkornot",
        info_plist={
            # Retina 的关键:不写这条,整个应用会跑在低分辨率放大模式里,猫是糊的。
            # 自检里的"遮罩与帧 alpha 吻合"会在高 DPI 下露馅,但糊不糊只有肉眼看得出来。
            "NSHighResolutionCapable": True,
            "CFBundleName": "drink_or_not",
            "CFBundleDisplayName": "drink_or_not",
            # 想让应用不进 Dock(纯菜单栏/托盘程序)就加 "LSUIElement": True。
            # 本次**刻意不加**:LSUIElement 会改掉激活策略,设置窗口还能不能正常拿到焦点
            # 只能在真机上验。先按普通 App 出,等虚拟机结果出来再决定要不要翻这个开关。
        },
    )
