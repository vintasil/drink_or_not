"""把各组件接起来。这里不写业务规则,只做连线和生命周期管理。"""

import logging

from PyQt5.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import config as config_mod
from . import messages, tracker
from .activity import IdleDetector
from .judge import CompletionJudge
from .pet_window import PetWindow
from .scheduler import Scheduler
from .settings_dialog import SettingsDialog
from .tray import Tray

log = logging.getLogger(__name__)

HELP_TEXT = """一只坐在魔法书上的猫,定时提醒你照顾自己。

左键拖动     把猫挪到任意位置,位置会自动记住
右键         设置 / 帮助 / 立即测试提醒 / 退出
左键点气泡   知道了。注意:点掉气泡不会中断"是否真去做了"的判定
托盘图标     显示或隐藏宠物,以及看今日完成情况

关于"是否真去做了":
  喝水、上厕所弹出提醒后,程序会盯着全局鼠标空闲时长。你起身去做事时鼠标会静止,
  静止时间达到阈值就记为完成。观察窗口结束后仍没达标就记为未完成。这是启发式的,
  坐着不动鼠标会被算作"去了",反过来起身时手碰到鼠标则不算。

喝水/上厕所的默认阈值:
  喝水    静止 20 秒即算去了,观察窗口 5 分钟
  上厕所  静止 120 秒即算去了,观察窗口 5 分钟

这两项的数据记在 records.jsonl,托盘菜单和文件里都能看到。"""


class Application:
    def __init__(self, app: QApplication, cfg: dict):
        self.app = app
        self.cfg = cfg

        self.detector = IdleDetector()
        self.judge = CompletionJudge(self.detector)
        self.scheduler = Scheduler(cfg, self.judge)
        self.pet = PetWindow(cfg)

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self.pet)
            self.tray.set_pet_visible(True)
        else:
            log.warning("系统没有托盘,宠物被藏起来就只能重启程序找回来了")

        self._wire()

    def _wire(self) -> None:
        self.scheduler.reminder.connect(self._on_reminder)
        self.scheduler.judged.connect(self._on_judged)

        self.pet.bubble_action.connect(self._on_bubble_action)
        self.pet.settings_requested.connect(self._open_settings)
        self.pet.help_requested.connect(self._show_help)
        self.pet.quit_requested.connect(self.quit)
        self.pet.test_requested.connect(self._test_reminder)

        if self.tray:
            self.tray.settings_requested.connect(self._open_settings)
            self.tray.help_requested.connect(self._show_help)
            self.tray.quit_requested.connect(self.quit)
            self.tray.test_requested.connect(self._test_reminder)
            self.tray.visibility_toggled.connect(self._toggle_visibility)

    def start(self) -> None:
        self.pet.show()
        if self.tray:
            self.tray.show()
        self.scheduler.start()
        if self.cfg["startup_message"]["enabled"]:
            self._on_reminder("startup", dry_run=True)

    # ---------- 提醒 ----------

    def _on_reminder(self, kind: str, dry_run: bool) -> None:
        if kind == "startup":
            text = f"{messages.EMOJI['startup']} {self.cfg['startup_message']['text']}"
        else:
            text = messages.format_bubble(kind)
        self.pet.show_bubble(kind, text)
        tracker.record_fired(kind, dry_run)
        self._refresh_stats()

    def _on_judged(self, kind: str, outcome: str, dry_run: bool) -> None:
        tracker.record_outcome(kind, outcome, dry_run)
        self._refresh_stats()
        # 气泡还停在屏幕上就顺手反馈一下;判"没去"就闭嘴,不做二次打扰
        if outcome == "completed" and self.pet.bubble.visible and self.pet.current_kind == kind:
            self.pet.show_bubble(kind, "✅ 记下了。", actions=(), seconds=4)

    def _on_bubble_action(self, kind: str, label: str) -> None:
        if label == "5 分钟后再提醒":
            self.scheduler.defer(kind)

    def _test_reminder(self, kind: str) -> None:
        self.scheduler.trigger(kind, dry_run=True)

    def _refresh_stats(self) -> None:
        if self.tray:
            self.tray.refresh_stats()

    # ---------- 界面 ----------

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.cfg, self.pet)
        dialog.saved.connect(self._apply_config)
        dialog.exec_()

    def _apply_config(self, cfg: dict) -> None:
        self.cfg = cfg
        try:
            config_mod.save(cfg)
        except OSError as exc:
            log.warning("保存配置失败: %s", exc)
        self.pet.apply_config(cfg)
        self.scheduler.apply_config(cfg)

    def _toggle_visibility(self) -> None:
        visible = not self.pet.isVisible()
        self.pet.setVisible(visible)
        if self.tray:
            self.tray.set_pet_visible(visible)

    def _show_help(self) -> None:
        box = QMessageBox(self.pet)
        box.setWindowTitle("drink_or_not 帮助")
        box.setText(HELP_TEXT)
        box.setIcon(QMessageBox.Information)
        box.exec_()

    def quit(self) -> None:
        self.scheduler.stop()
        self.pet.save_position()
        try:
            config_mod.save(self.cfg)
        except OSError as exc:
            log.warning("退出时保存配置失败: %s", exc)
        if self.tray:
            self.tray.hide()
        self.app.quit()
