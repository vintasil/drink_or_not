"""开机自启。三个平台各写各的地方:

    Linux    ~/.config/autostart/drink-or-not.desktop
    Windows  HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
    macOS    ~/Library/LaunchAgents/com.drinkornot.plist
"""

import logging
import os
import plistlib
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LINUX_NAME = "drink-or-not.desktop"
MACOS_LABEL = "com.drinkornot"
WINDOWS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_NAME = "drink_or_not"


def install_command() -> str:
    """怎么把本程序拉起来。打包后就是可执行文件本身,否则走模块入口。"""
    exe = sys.executable
    if getattr(sys, "frozen", False):
        return f'"{exe}"'
    return f'"{exe}" -m drink_or_not'


def _linux_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / LINUX_NAME


def _macos_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_KEY) as key:
                winreg.QueryValueEx(key, WINDOWS_NAME)
                return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return _macos_path().exists()
    return _linux_path().exists()


def set_enabled(enabled: bool) -> bool:
    """返回是否设置成功。失败只记日志,不让设置窗口崩掉。"""
    try:
        if sys.platform == "win32":
            return _set_windows(enabled)
        if sys.platform == "darwin":
            return _set_macos(enabled)
        return _set_linux(enabled)
    except Exception as exc:
        log.warning("设置开机自启失败: %s", exc)
        return False


def _set_linux(enabled: bool) -> bool:
    path = _linux_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=drink_or_not\n"
        "Comment=桌面宠物:定时提醒喝水、上厕所、吃饭、休息\n"
        f"Exec={install_command()}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    return True


def _set_windows(enabled: bool) -> bool:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, WINDOWS_NAME, 0, winreg.REG_SZ, install_command())
        else:
            try:
                winreg.DeleteValue(key, WINDOWS_NAME)
            except FileNotFoundError:
                pass
    return True


def _set_macos(enabled: bool) -> bool:
    path = _macos_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": MACOS_LABEL,
        "ProgramArguments": [sys.executable] + ([] if getattr(sys, "frozen", False) else ["-m", "drink_or_not"]),
        "RunAtLoad": True,
    }
    with path.open("wb") as fh:
        plistlib.dump(payload, fh)
    return True
