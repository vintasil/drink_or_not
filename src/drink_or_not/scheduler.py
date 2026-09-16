"""提醒调度:间隔倒计时 + 每天固定时刻的日报 + 免打扰。

日报不用"算出到下一个 18 点还有多少毫秒"那种一次性定时器 —— 系统休眠、手动改
时间、时区切换都会让它算错。改成 30 秒轮询一次"目标时刻是不是已经过了且今天还没
报过",这些情况全部自然覆盖。
"""

import logging
from datetime import datetime, time as dtime
from typing import Dict, List

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from . import config as config_mod

log = logging.getLogger(__name__)

REPORT_POLL_MS = 30_000
DEFER_MINUTES = 5


def _parse_hhmm(value: str) -> dtime:
    hour, _, minute = str(value).partition(":")
    return dtime(int(hour) % 24, int(minute) % 60)


class Scheduler(QObject):
    reminder = pyqtSignal(str, bool)  # (kind, dry_run)
    judged = pyqtSignal(str, str, bool)  # (kind, outcome, dry_run)

    def __init__(self, cfg: dict, judge, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.judge = judge
        self._timers: Dict[str, QTimer] = {}
        self._deferred: List[QTimer] = []
        self._last_report_date = None

        self._report_timer = QTimer(self)
        self._report_timer.setInterval(REPORT_POLL_MS)
        self._report_timer.timeout.connect(self._poll_report)

        judge.finished.connect(self.judged)

    # ---------- 生命周期 ----------

    def start(self) -> None:
        now = datetime.now()
        target = _parse_hhmm(self.cfg["daily_report"]["time"])
        # 启动时如果已经过了今天的目标时刻,当成今天已经报过,免得一开机就弹
        self._last_report_date = now.date() if now.time() >= target else None
        self._arm_interval_timers()
        if self.cfg["daily_report"]["enabled"]:
            self._report_timer.start()

    def stop(self) -> None:
        for timer in self._timers.values():
            timer.stop()
        for timer in self._deferred:
            timer.stop()
        self._deferred.clear()
        self._report_timer.stop()
        self.judge.cancel()

    def apply_config(self, cfg: dict) -> None:
        was_reporting = self._report_timer.isActive()
        self.cfg = cfg
        self._arm_interval_timers()
        if cfg["daily_report"]["enabled"] and not was_reporting:
            self._report_timer.start()
        elif not cfg["daily_report"]["enabled"]:
            self._report_timer.stop()

    def _arm_interval_timers(self) -> None:
        for kind in config_mod.REMINDER_KEYS:
            item = self.cfg["reminders"][kind]
            timer = self._timers.get(kind)
            if timer is not None:
                timer.stop()
            if not item["enabled"] or item["interval_min"] <= 0:
                continue
            if timer is None:
                timer = QTimer(self)
                timer.timeout.connect(lambda k=kind: self._fire(k))
                self._timers[kind] = timer
            timer.start(max(1, item["interval_min"]) * 60_000)

    # ---------- 触发 ----------

    def trigger(self, kind: str, dry_run: bool = True) -> None:
        """设置里/菜单里手动测一次。默认 dry_run,不写记录。"""
        if kind == "daily_report":
            self._last_report_date = datetime.now().date()
        self._fire(kind, dry_run=dry_run)

    def defer(self, kind: str, minutes: int = DEFER_MINUTES) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._fire(kind))
        timer.start(minutes * 60_000)
        self._deferred.append(timer)

    def _fire(self, kind: str, dry_run: bool = False) -> None:
        if not dry_run and self._in_quiet_hours():
            log.info("免打扰时段,跳过 %s 提醒", kind)
            return
        item = self.cfg["reminders"].get(kind)
        if item and item.get("track"):
            self.judge.watch(
                kind,
                item.get("idle_threshold_sec", 20),
                item.get("window_sec", 300),
                dry_run,
            )
        self.reminder.emit(kind, dry_run)

    def _poll_report(self) -> None:
        spec = self.cfg["daily_report"]
        if not spec["enabled"]:
            return
        now = datetime.now()
        if now.time() < _parse_hhmm(spec["time"]):
            return
        if self._last_report_date == now.date():
            return
        self._last_report_date = now.date()
        if self._in_quiet_hours():
            log.info("免打扰时段,跳过今日日报提醒")
            return
        self.reminder.emit("daily_report", False)

    def _in_quiet_hours(self) -> bool:
        spec = self.cfg["quiet_hours"]
        if not spec["enabled"]:
            return False
        start = _parse_hhmm(spec["start"])
        end = _parse_hhmm(spec["end"])
        now = datetime.now().time()
        if start <= end:
            return start <= now < end
        return now >= start or now < end  # 跨零点,比如 22:00-08:00
