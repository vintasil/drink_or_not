"""设置窗口 / 自启 / 气泡命中 / 形象素材库 这几块的离线冒烟。

e2e_test.py 只跑到"调度→判定→记录",这里补上剩下没被跑到的部分:设置窗口改完
能不能原样收回来、自启写没写对地方、气泡按钮的命中区对不对、导入的形象能不能
落盘/加载/切换/删除。

    uv run python script/ui_test.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="drink_ui_")
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PIL import Image, ImageDraw  # noqa: E402
from PyQt5.QtCore import QPoint, QRect, QTime  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from drink_or_not import autostart, config as config_mod  # noqa: E402
from drink_or_not import resources, sprite_convert, sprite_library  # noqa: E402
from drink_or_not.bubble import Bubble  # noqa: E402
from drink_or_not.pet_window import PetWindow, SpriteSet  # noqa: E402
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
# 跟内置 manifest 的 canvas 比,别写死数字:写死过一版 428 其实抄的是高度不是宽度
builtin_canvas = json.loads((resources.assets_dir() / "manifest.json").read_text(encoding="utf-8"))["canvas"]
check(
    [pet.sprites.canvas.width(), pet.sprites.canvas.height()] == builtin_canvas,
    "画布按 1.0 重算",
    f"{pet.sprites.canvas.width()}x{pet.sprites.canvas.height()}",
)

# 跨屏记忆:换过显示器后保存的位置要能回落到默认位
off_screen = config_mod.deep_merge(tight, {"pet": {"pos": [99999, 99999]}})
pet.apply_config(off_screen)
pet.restore_position()
check(pet._on_screen(pet.pos()), "离屏坐标被纠正回可见区", str((pet.pos().x(), pet.pos().y())))

before = config_mod.load()["pet"]["pos"]
pet.save_position()
check(config_mod.load()["pet"]["pos"] == before, "save_position 只改内存,不写盘")

# ---------- 形象素材库 ----------
print("\n[形象素材库]")
initial = sprite_library.list_sprites()
check(len(initial) == 1 and initial[0].id == "default", "初始只有内置形象", str([s.id for s in initial]))
check(initial[0].builtin is True, "内置形象带 builtin 标记")
check(sprite_library.sprite_dir("default") == resources.assets_dir(), "内置形象直接指向随包 assets")

# 纯色背景 + 主体:走抠图这条路
plain = Path(TMP) / "plain.png"
img = Image.new("RGB", (160, 160), (255, 255, 255))
ImageDraw.Draw(img).ellipse((40, 30, 120, 130), fill=(200, 60, 60))
img.save(plain)

prepared = sprite_convert.prepare(plain)
check(not prepared.problems, "纯色背景抠图通过自检", "; ".join(prepared.problems))
check(not prepared.used_alpha, "RGB 输入没走 alpha 那条路")
check(len(prepared.frames) == sprite_convert.COUNT, "生成了 36 帧", str(len(prepared.frames)))

info = sprite_library.install(prepared, "测试形象")
check(info.id != "default", "落盘拿到新 id", info.id)
check((sprite_library.sprite_dir(info.id) / "manifest.json").is_file(), "manifest 已写出")
check((sprite_library.sprite_dir(info.id) / "source.png").is_file(), "原图已存档,便于重新转换")
check(
    len(list((sprite_library.sprite_dir(info.id) / "frames").glob("*.png"))) == sprite_convert.COUNT,
    "帧文件数量对",
)
check(not list(sprite_library.sprites_root().glob("*" + sprite_library.PART_SUFFIX)), "没有残留的 .part 目录")

listed = sprite_library.list_sprites()
check(len(listed) == 2 and listed[0].id == "default", "新形象排在内置之后", str([s.id for s in listed]))
check(listed[1].name == "测试形象", "显示名来自 manifest", listed[1].name)

# 重名:目录加 -2 后缀,显示名必须跟着变,否则菜单里两个条目长得一模一样
dup = sprite_library.install(prepared, "测试形象")
check(dup.id != info.id, "重名拿到不同的 id", f"{info.id} / {dup.id}")
check(dup.name == dup.id, "重名的显示名跟着 id 走", dup.name)
check([s.name for s in sprite_library.list_sprites()] == ["魔法猫（内置）", "测试形象", dup.id], "菜单里三个名字互不相同")
sprite_library.delete_sprite(dup.id)

custom_manifest = json.loads(
    (sprite_library.sprite_dir(info.id) / "manifest.json").read_text(encoding="utf-8")
)
custom = SpriteSet.load(info.id, 1.0)
check(
    [custom.canvas.width(), custom.canvas.height()] == custom_manifest["canvas"],
    "自定义形象能加载,画布与 manifest 一致",
    f"{custom.canvas.width()}x{custom.canvas.height()}",
)

# 换到自定义形象,再换回来
pet.apply_config(config_mod.deep_merge(tight, {"pet": {"sprite": info.id}}))
qapp.processEvents()
check(pet.sprite_id == info.id, "宠物切到自定义形象")
check(not pet.mask().isEmpty(), "自定义形象的遮罩非空")
pet.apply_config(config_mod.deep_merge(tight, {"pet": {"sprite": "default"}}))
check(pet.sprite_id == "default", "能切回内置")

# 透明底 PNG:直接采用自带 alpha,跳过抠图
clear = Path(TMP) / "clear.png"
rgba = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
ImageDraw.Draw(rgba).rectangle((30, 30, 90, 90), fill=(20, 120, 220, 255))
rgba.save(clear)
with_alpha = sprite_convert.prepare(clear)
check(with_alpha.used_alpha, "透明底 PNG 走 alpha,不抠背景")
check(not with_alpha.problems, "自带 alpha 跳过自检")

# 全透明图:得明确报错,不能塞一张空图给用户
blank = Path(TMP) / "blank.png"
Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(blank)
try:
    sprite_convert.prepare(blank)
    check(False, "全透明图应当报错")
except sprite_convert.ConversionError as exc:
    check(True, "全透明图报 ConversionError", str(exc))

# 左红右红、中间一整条背景色:抠完剩下的两块都贴着左右边界,自检必须拦下
band = Path(TMP) / "band.png"
grad = Image.new("RGB", (96, 96))
grad.putdata([(x * 255 // 95, 128, 200) for _ in range(96) for x in range(96)])
grad.save(band)
risky = sprite_convert.prepare(band)
check(bool(risky.problems), "贴边的抠图结果被自检拦下", "; ".join(risky.problems))

# 兜底:不抠图,整张图当形象
whole = sprite_convert.prepare(band, whole=True)
check(not whole.problems, "整图显示不做自检")
whole_cut = sprite_convert.cutout_image(band, whole=True)
check(whole_cut.getchannel("A").getextrema() == (255, 255), "整图显示的 alpha 铺满")

# 重命名只改显示名,目录名(id)不许动
sprite_library.rename_sprite(info.id, "改过名的猫")
check(sprite_library.list_sprites()[1].name == "改过名的猫", "重命名生效")
check(sprite_library.sprite_dir(info.id).is_dir(), "重命名没动目录名")
try:
    sprite_library.rename_sprite("default", "换个名")
    check(False, "内置形象不该能重命名")
except ValueError:
    check(True, "内置形象拒绝重命名")

try:
    sprite_library.delete_sprite("default")
    check(False, "内置形象不该能删")
except ValueError:
    check(True, "内置形象拒绝删除")

check(sprite_library.ensure_available("早就不在了") == "default", "不存在的形象退回内置")
sprite_library.delete_sprite(info.id)
check(sprite_library.ensure_available(info.id) == "default", "删掉后自动退回内置")
check(len(sprite_library.list_sprites()) == 1, "列表回到只剩内置")

print()
if failures:
    print(f"失败 {len(failures)} 项: {failures}")
    sys.exit(1)
print("全部通过")
sys.exit(0)
