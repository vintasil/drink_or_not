"""设置窗口 / 自启 / 气泡命中 这三块的离线冒烟。

e2e_test.py 只跑到"调度→判定→记录",这里补上剩下没被跑到的部分:设置窗口改完
能不能原样收回来、自启写没写对地方、气泡按钮的命中区对不对。

    uv run python script/ui_test.py
"""

import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="drink_ui_")
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt5.QtCore import QPoint, QRect, QTime  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from drink_or_not import autostart, config as config_mod  # noqa: E402
from drink_or_not.bubble import Bubble  # noqa: E402
from drink_or_not.pet_window import PetWindow  # noqa: E402
from drink_or_not.settings_dialog import SettingsDialog  # noqa: E402

failures = []


def check(ok, label, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


qapp = QApplication(sys.argv)

# ---------- 设置窗口:改一遍 → collect → 存盘 → 读回 ----------
print("\n[设置窗口]")
cfg = config_mod.load()
dlg = SettingsDialog(cfg)

dlg.w_scale.setValue(1.2)
dlg.w_on_top.setChecked(False)
dlg.w_region.setCurrentIndex(dlg.w_region.findData("rect"))
dlg.w_bubble_secs.setValue(45)
dlg.w_water_enabled.setChecked(False)
dlg.w_water_interval.setValue(7)
dlg.w_water_threshold.setValue(55)
dlg.w_water_window.setValue(120)
dlg.w_toilet_interval.setValue(99)
dlg.w_report_enabled.setChecked(True)
dlg.w_report_time.setTime(QTime(19, 30))
dlg.w_startup_text.setText("  今天也要活着  ")
dlg.w_quiet_enabled.setChecked(True)
dlg.w_quiet_start.setTime(QTime(23, 15))
dlg.w_quiet_end.setTime(QTime(7, 45))

collected = dlg._collect()
check(collected["pet"]["scale"] == 1.2, "pet.scale", str(collected["pet"]["scale"]))
check(collected["pet"]["always_on_top"] is False, "pet.always_on_top")
check(collected["pet"]["click_region"] == "rect", "pet.click_region")
check(collected["pet"]["bubble_seconds"] == 45, "pet.bubble_seconds")
check(collected["reminders"]["water"]["enabled"] is False, "water.enabled")
check(collected["reminders"]["water"]["interval_min"] == 7, "water.interval_min")
check(collected["reminders"]["water"]["idle_threshold_sec"] == 55, "water.idle_threshold_sec")
check(collected["reminders"]["water"]["window_sec"] == 120, "water.window_sec")
check(collected["reminders"]["toilet"]["interval_min"] == 99, "toilet.interval_min")
check(collected["reminders"]["toilet"]["idle_threshold_sec"] == 120, "toilet 阈值未被水改动波及")
check(collected["reminders"]["meal"]["track"] is False, "meal 没有 track 字段被凭空加上")
check(collected["daily_report"]["time"] == "19:30", "daily_report.time")
check(collected["startup_message"]["text"] == "今天也要活着", "启动语去掉了首尾空格")
check(collected["quiet_hours"]["enabled"] is True, "quiet_hours.enabled")
check(collected["quiet_hours"]["start"] == "23:15", "quiet_hours.start")
check(collected["quiet_hours"]["end"] == "07:45", "quiet_hours.end,补零")

config_mod.save(collected)
reloaded = config_mod.load()
check(reloaded["reminders"]["water"]["idle_threshold_sec"] == 55, "存盘后读回一致")
check(reloaded["quiet_hours"]["end"] == "07:45", "跨零点时间原样保留")

# 恢复默认按钮对应的路径
reset_cfg = config_mod.deep_merge(config_mod.DEFAULTS, {})
check(reset_cfg["reminders"]["toilet"]["idle_threshold_sec"] == 120, "恢复默认拿到 120s")

# ---------- 自启 ----------
print("\n[开机自启]")
check(autostart.is_enabled() is False, "初始未开启")
check(autostart.set_enabled(True) is True, "开启成功")
check(autostart.is_enabled() is True, "开启后状态为真")
desktop = autostart._linux_path()
check(desktop.exists(), "写到了 autostart 目录", str(desktop))
body = desktop.read_text(encoding="utf-8")
check("[Desktop Entry]" in body and "Type=Application" in body, "内容含 Desktop Entry")
check(f"Exec={autostart.install_command()}" in body, "Exec 指向本解释器", autostart.install_command())
check(autostart.set_enabled(False) is True, "关闭成功")
check(not desktop.exists(), "关闭后文件被删掉")

# ---------- 气泡命中 ----------
print("\n[气泡按钮命中]")
bubble = Bubble()
area = QRect(0, 0, 360, 150)
bubble.layout(area, "💧 你已经三小时没喝水了,勇士。", ("知道了", "5 分钟后再提醒"), tail_x=180)
check(bubble.visible, "layout 后 visible")
check(len(bubble.buttons) == 2, "排出了两个按钮", str([b for b, _ in bubble.buttons]))
check(bubble.button_at(QPoint(2, 2)) is None, "气泡外的点不命中按钮")
check(bubble.body.contains(QPoint(2, 2)) is False, "左上角落在气泡外")
for label, rect in bubble.buttons:
    check(bubble.button_at(rect.center()) == label, f"命中「{label}」", str(bubble.button_at(rect.center())))
    check(bubble.body.contains(rect), f"「{label}」按钮在气泡正文内")
check(
    bubble.buttons[0][1].right() < bubble.buttons[1][1].left(),
    "两个按钮不重叠,左一右二",
)
check(bubble.tail_tip.y() == bubble.body.bottom() + 10, "尾巴尖贴着气泡底边")

# ---------- 宠物窗口 ----------
print("\n[宠物窗口]")
# 上面存的是 rect 模式,这里手动改回 tight 才能看到遮罩
tight = config_mod.deep_merge(reloaded, {"pet": {"click_region": "tight", "scale": 0.6, "pos": None}})
pet = PetWindow(tight)
qapp.processEvents()
mask = pet.mask()
check(not mask.isEmpty(), "tight 模式遮罩非空", f"{mask.boundingRect().width()}x{mask.boundingRect().height()}")
check(pet.current_kind == "", "初始没有气泡")

cat_center = pet._cat_origin + QPoint(pet.sprites.canvas.width() // 2, pet.sprites.canvas.height() // 2)
check(mask.contains(cat_center), "猫身中心在遮罩内(可拖)")
check(not mask.contains(QPoint(3, 3)), "气泡区左上角不在遮罩内(可点穿)")
empty_slot = QPoint(pet.win_w - 3, pet._cat_origin.y() + 5)
check(not mask.contains(empty_slot), "猫旁边的透明区可点穿", str(empty_slot))

pet.show_bubble("water", "💧 测试", seconds=30)
qapp.processEvents()
check(pet.current_kind == "water", "show_bubble 后 current_kind")
check(pet.bubble.visible, "气泡可见")
with_bubble = pet.mask()
check(with_bubble.contains(pet.bubble.body.center()), "气泡本体进了遮罩(按钮可点)")
check(with_bubble.contains(cat_center), "猫身仍在遮罩内")

pet.hide_bubble()
qapp.processEvents()
check(pet.current_kind == "water", "hide_bubble 不负责清 kind(由调用方决定)")
check(not pet.bubble.visible, "气泡已隐藏")
check(not pet.mask().contains(pet.bubble.body.center()), "隐藏后气泡区重新可点穿")

# rect 模式:整窗接收点击,不该再有遮罩
rect_cfg = config_mod.deep_merge(tight, {"pet": {"click_region": "rect"}})
pet.apply_config(rect_cfg)
check(pet.mask().isEmpty(), "rect 模式遮罩被清掉(整窗可点)")
pet.apply_config(tight)
check(not pet.mask().isEmpty(), "切回 tight 遮罩恢复")

# 热重载:改缩放后画布重算
old_w = pet.win_w
grow = config_mod.deep_merge(tight, {"pet": {"scale": 1.0}})
pet.apply_config(grow)
check(pet.win_w > old_w, "放大后窗口变宽", f"{old_w} → {pet.win_w}")
check(pet.sprites.canvas.width() == round(428 * 1.0), "画布按 1.0 重算", str(pet.sprites.canvas.width()))

# 跨屏记忆:换过显示器后保存的位置要能回落到默认位
off_screen = config_mod.deep_merge(tight, {"pet": {"pos": [99999, 99999]}})
pet.apply_config(off_screen)
pet.restore_position()
check(pet._on_screen(pet.pos()), "离屏坐标被纠正回可见区", str((pet.pos().x(), pet.pos().y())))

before = config_mod.load()["pet"]["pos"]
pet.save_position()
check(config_mod.load()["pet"]["pos"] == before, "save_position 只改内存,不写盘")

print()
if failures:
    print(f"失败 {len(failures)} 项: {failures}")
    sys.exit(1)
print("全部通过")
sys.exit(0)
