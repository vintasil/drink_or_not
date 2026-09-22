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

# 图标由 script/make_icon.py 从 pic/cat/magic_cat.png 现做,仓库里不存二进制,
# build_macos.sh 会在打包前先跑一遍。Linux 的 ELF 没有"图标"这回事(.desktop 自己带),
# 所以只在 darwin 传;传了也不看,反而多一个"文件不存在"的坑。
ICON = str(ROOT / "build" / "icon.icns") if sys.platform == "darwin" else None

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
    icon=ICON,
)

if sys.platform == "darwin":
    # .app 外壳。裸 Mach-O 也能跑,但别人拿到只能开终端敲命令;套上 .app 才能双击启动、
    # 有图标、走 Launch Services。Windows/Linux 不产外壳,这个分支在那边完全不执行。
    app = BUNDLE(
        exe,
        name="drink_or_not.app",
        icon=ICON,  # Dock / Finder 里显示的就是它;少了这条是 PyInstaller 自带的默认图标
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
