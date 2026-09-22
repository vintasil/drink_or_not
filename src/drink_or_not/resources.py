"""定位随包资源。PyInstaller 单文件模式会把资源解到 sys._MEIPASS。"""

import sys
from pathlib import Path


def assets_dir() -> Path:
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "assets"
    # wheel 里 assets 被 force-include 到了包内(pyproject.toml),uv tool install /
    # uvbox 装出来的就是这一份;仓库里没有 src/drink_or_not/assets,所以源码运行会落到下面。
    packaged = Path(__file__).resolve().parent / "assets"
    if (packaged / "manifest.json").is_file():
        return packaged
    return Path(__file__).resolve().parents[2] / "assets"
