"""定位随包资源。PyInstaller 单文件模式会把资源解到 sys._MEIPASS。"""

import sys
from pathlib import Path


def assets_dir() -> Path:
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"
