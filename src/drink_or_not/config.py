"""配置读写。

放在各平台的标准配置目录下,规则简单到不值得引入 platformdirs:
    Linux    $XDG_CONFIG_HOME/drink_or_not/   (默认 ~/.config)
    Windows  %APPDATA%\\drink_or_not\\
    macOS    ~/Library/Application Support/drink_or_not/

读取时和 DEFAULTS 做深合并,所以升级后新增的配置项会自动带上默认值,老配置文件不会失效。
"""

import copy
import json
import os
import sys
from pathlib import Path

APP_DIR = "drink_or_not"
CONFIG_FILE = "config.json"
RECORDS_FILE = "records.jsonl"

REMINDER_KEYS = ("water", "toilet", "meal", "rest", "slack")
REMINDER_LABELS = {
    "water": "喝水",
    "toilet": "上厕所",
    "meal": "吃饭",
    "rest": "休息",
    "slack": "摸鱼",
}

DEFAULTS = {
    "version": 1,
    "pet": {
        "scale": 0.8,
        "pos": None,  # None = 首次启动时落到屏幕右下角
        "always_on_top": True,
        "click_region": "tight",  # tight = 贴合猫形点击穿透;rect = 整窗接收点击
        "bubble_seconds": 30,
    },
    "reminders": {
        "water": {
            "enabled": True,
            "interval_min": 45,
            "track": True,
            "idle_threshold_sec": 20,
            "window_sec": 300,
        },
        "toilet": {
            "enabled": True,
            "interval_min": 60,
            "track": True,
            "idle_threshold_sec": 120,
            "window_sec": 300,
        },
        "meal": {"enabled": True, "interval_min": 240, "track": False},
        "rest": {"enabled": True, "interval_min": 90, "track": False},
        "slack": {"enabled": False, "interval_min": 60, "track": False},
    },
    "daily_report": {"enabled": True, "time": "18:00"},
    "startup_message": {"enabled": True, "text": "记得给手机充满电哦"},
    "quiet_hours": {"enabled": False, "start": "22:00", "end": "08:00"},
    "autostart": False,
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR


def config_path() -> Path:
    return config_dir() / CONFIG_FILE


def records_path() -> Path:
    return config_dir() / RECORDS_FILE


def deep_merge(base: dict, override: dict) -> dict:
    """把 override 叠到 base 上,只递归 dict;其余类型直接替换。"""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    """读配置。文件不存在或损坏都退回默认值,不能让宠物起不来。"""
    path = config_path()
    if not path.exists():
        cfg = copy.deepcopy(DEFAULTS)
        try:
            # 首次运行就落一份盘,免得用户想手改配置时找不到文件
            save(cfg)
        except OSError:
            pass
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULTS)
    return deep_merge(DEFAULTS, data)


def save(cfg: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)  # 原子替换,避免写一半掉电留下半个文件
