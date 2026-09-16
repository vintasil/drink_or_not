"""判断用户是不是真的离开工位去做了(喝水/上厕所)。

只看一个信号:全局鼠标空闲了多久。人起身去接水,鼠标必然静止一段时间。

难点在于提醒弹出的那一刻,用户往往**本来就**处于静止状态 —— 正在看代码、看文档,
鼠标好几十秒没动过是常态。所以不能只看"idle >= 阈值",否则弹出瞬间就误判成完成;
但也不能要求"静止完全发生在弹出之后"(即 idle <= now - 弹出时刻),因为那在这种
常见情况下永远不成立 —— idle 会一直大于已过去的时长,完成判定永远触发不了。

正确的口径是只统计**提醒之后新增**的静止时长。记下弹出时的 idle 作为基准:

    fresh = idle - 基准      若 idle >= 基准(说明这段时间一直没输入,静止是连续累加的)
    fresh = idle             若 idle <  基准(说明中途有输入,idle 被重置成了新的一段)

    fresh >= 阈值 -> 完成

这样"弹出时已静止 60 秒、随后起身离开"的人,再静止 20 秒就会被记上;而一直坐在
工位前晃鼠标的人永远攒不够 fresh。至于"本来就离开座位了"被算作完成 —— 那本来就
是期望的结果,无害。

判据是启发式的,一定会误判:坐着不动鼠标超过阈值会被算作"去了"。这是不引入额外
依赖的前提下能做到的上限。
"""

import logging
import time
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

log = logging.getLogger(__name__)

POLL_MS = 1000


class CompletionJudge(QObject):
    finished = pyqtSignal(str, str, bool)  # (kind, "completed"|"missed", dry_run)

    def __init__(self, detector, parent=None):
        super().__init__(parent)
        self.detector = detector
        self._kind: Optional[str] = None
        self._threshold = 0.0
        self._window = 0.0
        self._started = 0.0
        self._baseline = 0.0
        self._dry_run = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def watching(self) -> Optional[str]:
        return self._kind

    def watch(self, kind: str, threshold_sec: float, window_sec: float, dry_run: bool = False) -> None:
        if not self.detector.available:
            log.warning("没有可用的空闲检测来源,跳过 %s 的完成判定", kind)
            return
        self.cancel()
        self._kind = kind
        self._threshold = float(threshold_sec)
        self._window = float(window_sec)
        self._dry_run = dry_run
        self._started = time.monotonic()
        self._baseline = self.detector.idle_seconds() or 0.0
        self._timer.start()
        log.info(
            "开始判定 %s:提醒后需再静止 %.0fs,观察窗口 %.0fs(弹出时已静止 %.0fs)",
            kind,
            self._threshold,
            self._window,
            self._baseline,
        )

    def cancel(self) -> None:
        self._timer.stop()
        self._kind = None

    def _tick(self) -> None:
        kind = self._kind
        if kind is None:
            self._timer.stop()
            return

        elapsed = time.monotonic() - self._started
        idle = self.detector.idle_seconds()

        if idle is not None:
            fresh = idle - self._baseline if idle >= self._baseline else idle
            if fresh >= self._threshold:
                log.info("%s 判定完成:提醒后静止 %.0fs(总空闲 %.0fs)", kind, fresh, idle)
                self._finish(kind, "completed")
                return
        if elapsed >= self._window:
            log.info("%s 判定未完成:%.0fs 窗口内没攒够静止时长", kind, self._window)
            self._finish(kind, "missed")

    def _finish(self, kind: str, outcome: str) -> None:
        dry_run = self._dry_run
        self.cancel()
        self.finished.emit(kind, outcome, dry_run)
