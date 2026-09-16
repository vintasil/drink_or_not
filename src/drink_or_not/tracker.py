"""提醒事件与完成情况的记录。

JSONL,一行一条,追加写。一次提醒最多产生两行:弹出时的 fired,以及判定结束时的
judged(只有喝水/上厕所这类开了 track 的才有第二行)。用显式的 event 字段区分,
免得统计时把同一件事数成两次。

只记事实不做索引 —— 文件一年也就几百 KB,读全量再过滤完全够用。
"""

import json
import logging
from datetime import datetime
from typing import Dict, Optional

from .config import records_path

log = logging.getLogger(__name__)

EVENT_FIRED = "fired"
EVENT_JUDGED = "judged"


def _append(entry: dict) -> None:
    path = records_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("写记录失败: %s", exc)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record_fired(item: str, dry_run: bool = False, **extra) -> None:
    if dry_run:
        return
    _append({"ts": _now(), "item": item, "event": EVENT_FIRED, **extra})


def record_outcome(item: str, outcome: str, dry_run: bool = False, **extra) -> None:
    if dry_run:
        return
    _append({"ts": _now(), "item": item, "event": EVENT_JUDGED, "outcome": outcome, **extra})


def today_summary() -> Dict[str, Dict[str, int]]:
    """今日各项:弹了几次、判定完成几次、判定没完成几次。"""
    path = records_path()
    if not path.exists():
        return {}
    today = datetime.now().astimezone().date().isoformat()
    summary: Dict[str, Dict[str, int]] = {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue  # 写到一半被杀留下的残行,跳过
                if not str(entry.get("ts", "")).startswith(today):
                    continue
                item = entry.get("item")
                if not item:
                    continue
                bucket = summary.setdefault(item, {"fired": 0, "completed": 0, "missed": 0})
                event = entry.get("event")
                if event == EVENT_FIRED:
                    bucket["fired"] += 1
                elif event == EVENT_JUDGED and entry.get("outcome") in ("completed", "missed"):
                    bucket[entry["outcome"]] += 1
    except OSError as exc:
        log.warning("读记录失败: %s", exc)
    return summary


def format_summary(summary: Dict[str, Dict[str, int]]) -> Optional[str]:
    """拼成托盘菜单里那一行。今天还没有记录时返回 None。"""
    from . import config as config_mod

    parts = []
    for key in config_mod.REMINDER_KEYS:
        bucket = summary.get(key)
        if not bucket or not bucket["fired"]:
            continue
        label = config_mod.REMINDER_LABELS[key]
        if bucket["completed"] or bucket["missed"]:
            parts.append(f"{label} {bucket['completed']}/{bucket['fired']}")
        else:
            parts.append(f"{label} ×{bucket['fired']}")
    return " · ".join(parts) if parts else None
