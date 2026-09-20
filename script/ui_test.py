"""设置窗口 / 自启 / 气泡命中 / 形象素材库 这几块的离线冒烟。

e2e_test.py 只跑到"调度→判定→记录",这里补上剩下没被跑到的部分:设置窗口改完
能不能原样收回来、自启写没写对地方、气泡按钮的命中区对不对、导入的形象能不能
落盘/加载/切换/删除。

    uv run python script/ui_test.py
"""

import json
import os
import plistlib
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="drink_ui_")
if sys.platform == "darwin":
    # macOS 忽略 XDG_CONFIG_HOME,config_dir() 看的是 ~/Library/Application Support
    os.environ["HOME"] = TMP
else:
    os.environ["XDG_CONFIG_HOME"] = TMP
if sys.platform.startswith("linux"):
    # 只有 X11/XWayland 需要钉死 xcb;macOS 上必须让 Qt 自己选 cocoa
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PIL import Image, ImageDraw  # noqa: E402
from PyQt5.QtCore import QPoint, QRect, Qt, QTime  # noqa: E402
from PyQt5.QtWidgets import QApplication, QWidget  # noqa: E402

from drink_or_not import activity, autostart, config as config_mod  # noqa: E402
from drink_or_not import resources, sprite_convert, sprite_library  # noqa: E402
from drink_or_not.bubble import Bubble  # noqa: E402
from drink_or_not.pet_window import PetWindow, SpriteSet, apply_window_flags  # noqa: E402
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

if sys.platform == "darwin":
    # macOS 写的是 LaunchAgent plist。临时 HOME 让 _macos_path() 落在临时目录里
    target = autostart._macos_path()
    check(target.exists(), "写到了 LaunchAgents 目录", str(target))
    body = plistlib.loads(target.read_bytes())
    check(body["Label"] == autostart.MACOS_LABEL, "Label 对", str(body["Label"]))
    check(body["RunAtLoad"] is True, "RunAtLoad 打开")
    check(
        body["ProgramArguments"][0] == sys.executable,
        "ProgramArguments 指向本解释器",
        str(body["ProgramArguments"]),
    )
    check(
        body["ProgramArguments"][len(body["ProgramArguments"]) - 2 :] == ["-m", "drink_or_not"],
        "未冻结时走模块入口",
        str(body["ProgramArguments"]),
    )
else:
    target = autostart._linux_path()
    check(target.exists(), "写到了 autostart 目录", str(target))
    body = target.read_text(encoding="utf-8")
    check("[Desktop Entry]" in body and "Type=Application" in body, "内容含 Desktop Entry")
    check(f"Exec={autostart.install_command()}" in body, "Exec 指向本解释器", autostart.install_command())

check(autostart.set_enabled(False) is True, "关闭成功")
check(not target.exists(), "关闭后文件被删掉")

# plist 的内容是纯函数,任何平台都能断言 —— 打包后路径要换成可执行文件本身
payload = autostart.macos_plist_payload(frozen=True, executable="/Applications/drink_or_not")
check(payload["ProgramArguments"] == ["/Applications/drink_or_not"], "冻结后不带 -m", str(payload))
check(payload["RunAtLoad"] is True, "RunAtLoad 始终打开")
check(payload["Label"] == autostart.MACOS_LABEL, "Label 用的是固定标识")
check(
    plistlib.loads(plistlib.dumps(payload)) == payload,
    "plist 能序列化并原样读回",
)

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

# ---------- macOS 移植:能在 Linux 上证的部分 ----------
# 真机行为(window 失活是否隐藏、全屏浮层、托盘点击语义、Retina 遮罩)只能在 Mac 上看。
# 这里只钉住纯逻辑,免得改了 darwin 分支却没人发现。
print("\n[macOS 移植]")


def provider_names(platform):
    """假 sys.platform 下取 provider 名字。只看名字,不调用 factory —— 不碰任何 mac 框架。"""
    real = sys.platform
    sys.platform = platform
    try:
        return [name for name, _ in activity._providers()]
    finally:
        sys.platform = real


darwin = provider_names("darwin")
check(darwin[0] == "macos/CGEventSourceSecondsSinceLastEventType", "darwin 首选 CoreGraphics", str(darwin))
check(len(darwin) == 2, "darwin 有兜底,不是单点", str(darwin))
check(darwin[-1] == "fallback/QCursor-poll", "darwin 兜底是 QCursor 轮询", str(darwin))
check("linux/mutter-idle-monitor" not in darwin, "darwin 不串到 Linux 的来源", str(darwin))
linux = provider_names("linux")
check(linux[0] == "linux/mutter-idle-monitor" and linux[-1] == "fallback/QCursor-poll", "Linux 链未受影响", str(linux))
check("macos/CGEventSourceSecondsSinceLastEventType" not in linux, "Linux 不串到 mac 的来源", str(linux))

# 探针窗口和真窗口必须共用同一份 flags,否则自检测的不是真东西
probe = QWidget()
apply_window_flags(probe)
check(bool(probe.windowFlags() & Qt.FramelessWindowHint), "apply_window_flags 设上了无边框")
check(bool(probe.windowFlags() & Qt.WindowStaysOnTopHint), "apply_window_flags 设上了置顶")
check(bool(probe.windowFlags() & Qt.Tool), "apply_window_flags 用了 Qt.Tool(不是 Qt.Window)")
check(probe.testAttribute(Qt.WA_TranslucentBackground), "apply_window_flags 设上了透明属性")
# 真窗口也走了同一份 apply_window_flags。只比它独占、且不会被配置改动的两位 ——
# WindowStaysOnTopHint 是"置顶"开关,apply_config 会按 always_on_top 把它打开/关掉,
# 比它会误报(上面的设置窗口测试恰好把它关了)。
shared = Qt.FramelessWindowHint | Qt.Tool
check(
    (pet.windowFlags() & shared) == shared,
    "真窗口走的是同一份 flags(不是各写各的)",
    str(int(pet.windowFlags() & shared)),
)

# darwin 那条分支在 Linux 上永远走不到,里面写错名字的话只有上 Mac 才会 AttributeError。
# 这里把 sys.platform 骗成 darwin 真跑一遍 —— 在 Linux 上设这个属性只是置个无效的位,不会炸。
check(hasattr(Qt, "WA_MacAlwaysShowToolWindow"), "PyQt5 里有 WA_MacAlwaysShowToolWindow")
real_platform = sys.platform
sys.platform = "darwin"
try:
    macprobe = QWidget()
    apply_window_flags(macprobe)
    mac_ok = macprobe.testAttribute(Qt.WA_MacAlwaysShowToolWindow)
    mac_err = ""
except Exception as exc:  # noqa: BLE001 — 就是要看它会不会炸
    mac_ok, mac_err = False, repr(exc)
finally:
    sys.platform = real_platform
check(mac_ok, "darwin 分支真的能跑通并设上属性", mac_err)
# WA_MacAlwaysShowToolWindow 在 Linux 上是 no-op(平台门控),它的真实验证在 check_env 的 darwin 分支

# ---------- 打包路线:assets 必须能跟着 wheel 走 ----------
# uvbox / uv tool install 装出来的目录里没有仓库根的 assets/,全靠 pyproject.toml 的
# force-include 把它映射进包内。这里把三种布局都摆出来,钉住 assets_dir() 的解析顺序。
print("\n[打包:assets 随包]")

# 从测试脚本自身推仓库根,不去问 resources —— 拿被测对象当基准就成了自证。
ROOT = Path(__file__).resolve().parents[1]


def assets_dir_as(package_file, meipass=None):
    """把 resources.__file__(必要时还有 sys._MEIPASS)指到别处,看 assets_dir() 解析到哪。"""
    real_file = resources.__file__
    had_meipass = hasattr(sys, "_MEIPASS")
    real_meipass = getattr(sys, "_MEIPASS", None)
    resources.__file__ = str(package_file)
    if meipass is not None:
        sys._MEIPASS = str(meipass)
    elif had_meipass:
        del sys._MEIPASS
    try:
        return resources.assets_dir()
    finally:
        resources.__file__ = real_file
        if had_meipass:
            sys._MEIPASS = real_meipass
        elif meipass is not None:
            del sys._MEIPASS


# 1) 仓库检出的现状:包目录里没有 assets/,应当落到仓库根。
#    这条同时防住"packaged 分支误判" —— 判错了会把源码运行也带偏。
check(resources.assets_dir() == ROOT / "assets", "源码运行时解析到仓库根 assets")
check((resources.assets_dir() / "manifest.json").is_file(), "仓库根那份确实有 manifest.json")

# 2) wheel 装出来的布局:assets 在包内,靠 __file__ 找到,不依赖 cwd。
with tempfile.TemporaryDirectory(prefix="drink_pkg_") as pkg:
    pkg = Path(pkg)
    (pkg / "assets" / "frames").mkdir(parents=True)
    (pkg / "assets" / "manifest.json").write_text("{}", encoding="utf-8")
    (pkg / "resources.py").write_text("", encoding="utf-8")
    check(assets_dir_as(pkg / "resources.py") == pkg / "assets", "装出来的包能靠 __file__ 找到 assets")

# 3) 冻结(PyInstaller):_MEIPASS 优先于包内那份。
with tempfile.TemporaryDirectory(prefix="drink_frozen_") as frozen, tempfile.TemporaryDirectory(
    prefix="drink_pkg_"
) as pkg:
    frozen, pkg = Path(frozen), Path(pkg)
    (frozen / "assets").mkdir(parents=True)
    (frozen / "assets" / "manifest.json").write_text("{}", encoding="utf-8")
    (pkg / "assets").mkdir(parents=True)
    (pkg / "assets" / "manifest.json").write_text("{}", encoding="utf-8")
    (pkg / "resources.py").write_text("", encoding="utf-8")
    check(
        assets_dir_as(pkg / "resources.py", meipass=frozen) == frozen / "assets",
        "冻结时 _MEIPASS 优先",
    )

# force-include 是上面第 2 条成立的唯一前提,被删掉的话只有真去 uvbox 打包才会发现。
# 这里不做真实构建(太慢),只确认声明还在 —— 标签如实写成"声明"。
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
check(
    '[tool.hatch.build.targets.wheel.force-include]' in pyproject and '"assets" = "drink_or_not/assets"' in pyproject,
    "pyproject 里声明了 assets 的 force-include",
)

print()
if failures:
    print(f"失败 {len(failures)} 项: {failures}")
    sys.exit(1)
print("全部通过")
sys.exit(0)
