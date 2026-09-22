"""系统托盘图标。宠物被拖出屏幕或者藏起来时,靠它找回来。"""

import logging

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon

from . import messages, tracker
from .pet_window import PetWindow, fill_sprite_menu

log = logging.getLogger(__name__)


class Tray(QSystemTrayIcon):
    settings_requested = pyqtSignal()
    help_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    test_requested = pyqtSignal(str)
    visibility_toggled = pyqtSignal()
    sprite_switch_requested = pyqtSignal(str)  # 形象 id
    sprite_import_requested = pyqtSignal()
    sprite_manage_requested = pyqtSignal()

    def __init__(self, pet: PetWindow, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.refresh_icon()
        self.setToolTip("drink_or_not")
        self._menu = self._build_menu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self.refresh_stats()

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        self._stats = QAction("今日: 还没有记录", menu)
        self._stats.setEnabled(False)
        menu.addAction(self._stats)
        menu.addSeparator()

        self._toggle = QAction("隐藏宠物", menu)
        self._toggle.triggered.connect(self.visibility_toggled.emit)
        menu.addAction(self._toggle)

        test = menu.addMenu("立即测试提醒")
        for key in ("water", "toilet", "meal", "rest", "slack", "daily_report", "startup"):
            # 菜单文字里不放 emoji:Qt5 画不出彩色 emoji 字体,只会显示成空心方框
            test.addAction(
                messages.TITLE[key],
                lambda _=False, k=key: self.test_requested.emit(k),
            )

        menu.addSeparator()
        # 这个菜单是常驻的,形象列表会变,所以每次弹出前重填一遍
        self._sprite_menu = menu.addMenu("更换形象")
        self._sprite_menu.aboutToShow.connect(self._fill_sprite_menu)

        menu.addSeparator()
        menu.addAction("设置…", self.settings_requested.emit)
        menu.addAction("帮助", self.help_requested.emit)
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        return menu

    def _fill_sprite_menu(self) -> None:
        menu = self._sprite_menu
        menu.clear()  # clear 会连同旧 QActionGroup 一起析构,单选状态由下面重建
        fill_sprite_menu(menu, self.pet.sprite_id, self.sprite_switch_requested.emit)
        menu.addSeparator()
        menu.addAction("导入图片…", self.sprite_import_requested.emit)
        menu.addAction("管理素材库…", self.sprite_manage_requested.emit)

    def refresh_icon(self) -> None:
        self.setIcon(QIcon(self.pet.sprites.frames[0]))

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.visibility_toggled.emit()

    def set_pet_visible(self, visible: bool) -> None:
        self._toggle.setText("隐藏宠物" if visible else "显示宠物")

    def refresh_stats(self) -> None:
        line = tracker.format_summary(tracker.today_summary())
        self._stats.setText(f"今日: {line}" if line else "今日: 还没有记录")
        self.setToolTip(f"drink_or_not\n{line}" if line else "drink_or_not")
