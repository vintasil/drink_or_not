"""设置窗口。改完点保存即写盘并热重载,不需要重启宠物。"""

import copy
import logging

from PyQt5.QtCore import QTime, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from . import autostart, config as config_mod, messages

log = logging.getLogger(__name__)

CLICK_REGION_LABELS = (("tight", "贴合猫形(周围点击穿透)"), ("rect", "整窗矩形(兼容性优先)"))


def _time_edit(value: str) -> QTimeEdit:
    hour, _, minute = value.partition(":")
    widget = QTimeEdit(QTime(int(hour), int(minute)))
    widget.setDisplayFormat("HH:mm")
    return widget


def _spin(minimum, maximum, value, suffix="") -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(int(value))
    if suffix:
        widget.setSuffix(suffix)
    return widget


class SettingsDialog(QDialog):
    saved = pyqtSignal(dict)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = copy.deepcopy(cfg)
        self.setWindowTitle("drink_or_not 设置")
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        tabs = QTabWidget(self)
        tabs.addTab(self._pet_tab(), "宠物")
        tabs.addTab(self._reminder_tab(), "提醒")
        tabs.addTab(self._misc_tab(), "通用")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        reset = buttons.addButton("恢复默认", QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._reset)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # ---------- 各页 ----------

    def _pet_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        pet = self.cfg["pet"]

        scale = QDoubleSpinBox()
        scale.setRange(0.4, 1.5)
        scale.setSingleStep(0.05)
        scale.setValue(float(pet["scale"]))
        scale.setDecimals(2)
        self.w_scale = scale
        form.addRow("宠物大小", scale)

        self.w_on_top = QCheckBox("总在最前面")
        self.w_on_top.setChecked(bool(pet["always_on_top"]))
        form.addRow("", self.w_on_top)

        self.w_region = QComboBox()
        for value, label in CLICK_REGION_LABELS:
            self.w_region.addItem(label, value)
        self.w_region.setCurrentIndex(max(0, self.w_region.findData(pet["click_region"])))
        form.addRow("可点击范围", self.w_region)

        self.w_bubble_secs = _spin(5, 600, pet["bubble_seconds"], " 秒")
        form.addRow("气泡停留", self.w_bubble_secs)
        form.addRow(QLabel("提示:改完大小后,猫会重新按新尺寸贴在屏幕右下角方向,可以再拖一次。"))
        return page

    def _reminder_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        for key in config_mod.REMINDER_KEYS:
            item = self.cfg["reminders"][key]
            # 标题里不放 emoji:Qt5 画不出彩色 emoji 字体,只会显示成空心方框
            box = QGroupBox(config_mod.REMINDER_LABELS[key])
            form = QFormLayout(box)

            enabled = QCheckBox("启用")
            enabled.setChecked(bool(item["enabled"]))
            form.addRow("", enabled)

            interval = _spin(1, 24 * 60, item["interval_min"], " 分钟")
            form.addRow("提醒间隔", interval)

            setattr(self, f"w_{key}_enabled", enabled)
            setattr(self, f"w_{key}_interval", interval)

            if item.get("track"):
                threshold = _spin(5, 3600, item["idle_threshold_sec"], " 秒不动鼠标")
                window = _spin(30, 3600, item["window_sec"], " 秒内")
                form.addRow("算作去过", threshold)
                form.addRow("观察窗口", window)
                setattr(self, f"w_{key}_threshold", threshold)
                setattr(self, f"w_{key}_window", window)
                form.addRow(QLabel("起身去做事时鼠标会静止,静止够久即记为「完成」。"))

            outer.addWidget(box)

        outer.addWidget(QLabel("这些都是「每隔多久」,从启动或上次提醒后重新计时。"))
        return page

    def _misc_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        report = QGroupBox("📝 写日报")
        rform = QFormLayout(report)
        self.w_report_enabled = QCheckBox("每天提醒写日报")
        self.w_report_enabled.setChecked(bool(self.cfg["daily_report"]["enabled"]))
        rform.addRow("", self.w_report_enabled)
        self.w_report_time = _time_edit(self.cfg["daily_report"]["time"])
        rform.addRow("提醒时刻", self.w_report_time)
        outer.addWidget(report)

        startup = QGroupBox("🔌 启动语")
        sform = QFormLayout(startup)
        self.w_startup_enabled = QCheckBox("启动时弹一句")
        self.w_startup_enabled.setChecked(bool(self.cfg["startup_message"]["enabled"]))
        sform.addRow("", self.w_startup_enabled)
        self.w_startup_text = QLineEdit(self.cfg["startup_message"]["text"])
        sform.addRow("内容", self.w_startup_text)
        outer.addWidget(startup)

        quiet = QGroupBox("🌙 免打扰")
        qform = QFormLayout(quiet)
        self.w_quiet_enabled = QCheckBox("该时段内不弹提醒")
        self.w_quiet_enabled.setChecked(bool(self.cfg["quiet_hours"]["enabled"]))
        qform.addRow("", self.w_quiet_enabled)
        self.w_quiet_start = _time_edit(self.cfg["quiet_hours"]["start"])
        self.w_quiet_end = _time_edit(self.cfg["quiet_hours"]["end"])
        qform.addRow("从", self.w_quiet_start)
        qform.addRow("到", self.w_quiet_end)
        outer.addWidget(quiet)

        self.w_autostart = QCheckBox("开机自动启动")
        self.w_autostart.setChecked(autostart.is_enabled())
        outer.addWidget(self.w_autostart)

        outer.addWidget(QLabel(f"配置与记录位置:{config_mod.config_dir()}"))
        outer.addStretch(1)
        return page

    # ---------- 动作 ----------

    def _collect(self) -> dict:
        cfg = copy.deepcopy(self.cfg)
        cfg["pet"]["scale"] = round(self.w_scale.value(), 2)
        cfg["pet"]["always_on_top"] = self.w_on_top.isChecked()
        cfg["pet"]["click_region"] = self.w_region.currentData()
        cfg["pet"]["bubble_seconds"] = self.w_bubble_secs.value()

        for key in config_mod.REMINDER_KEYS:
            item = cfg["reminders"][key]
            item["enabled"] = getattr(self, f"w_{key}_enabled").isChecked()
            item["interval_min"] = getattr(self, f"w_{key}_interval").value()
            if item.get("track"):
                item["idle_threshold_sec"] = getattr(self, f"w_{key}_threshold").value()
                item["window_sec"] = getattr(self, f"w_{key}_window").value()

        cfg["daily_report"]["enabled"] = self.w_report_enabled.isChecked()
        cfg["daily_report"]["time"] = self.w_report_time.time().toString("HH:mm")
        cfg["startup_message"]["enabled"] = self.w_startup_enabled.isChecked()
        cfg["startup_message"]["text"] = self.w_startup_text.text().strip() or config_mod.DEFAULTS["startup_message"]["text"]
        cfg["quiet_hours"]["enabled"] = self.w_quiet_enabled.isChecked()
        cfg["quiet_hours"]["start"] = self.w_quiet_start.time().toString("HH:mm")
        cfg["quiet_hours"]["end"] = self.w_quiet_end.time().toString("HH:mm")
        return cfg

    def _save(self) -> None:
        cfg = self._collect()
        want_autostart = self.w_autostart.isChecked()
        if want_autostart != autostart.is_enabled() and not autostart.set_enabled(want_autostart):
            QMessageBox.warning(self, "开机自启", "写入自启项失败,其余设置仍然会保存。")
        cfg["autostart"] = want_autostart
        try:
            config_mod.save(cfg)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", f"写配置文件出错:{exc}")
            return
        self.cfg = cfg
        self.saved.emit(cfg)
        self.accept()

    def _reset(self) -> None:
        if QMessageBox.question(self, "恢复默认", "把所有设置恢复成默认值?") == QMessageBox.Yes:
            self.cfg = copy.deepcopy(config_mod.DEFAULTS)
            self.saved.emit(self.cfg)
            config_mod.save(self.cfg)
            self.accept()
