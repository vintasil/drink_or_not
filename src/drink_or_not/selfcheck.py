"""环境自检:确认桌面宠物赖以成立的几件事在本机真的能跑。

逻辑本体放在包里(不是 script/ 下),因为**打包产物也必须能跑这一份** —— uvbox/PyInstaller
打出来的东西在目标机上没法跑仓库脚本,而移植到新平台(尤其 macOS)时,能逐项验证比"猫出来了
没有"决定性得多。script/check_env.py 是它的薄壳。

检查项(任何一项 FAIL,对应的功能就是不可用的):

  1. Qt 平台插件          Linux 上能不能走 xcb(XWayland)—— Wayland 原生下窗口无法自行
                          定位,宠物就拖不动;macOS 上必须是 cocoa,走了 xcb 说明串到 XQuartz。
  2. 无边框透明窗口        会不会真的透明,还是糊一块不透明方块。
  3. 窗口定位              move() 之后窗口是不是真到了那个坐标。
  4. alpha 点击遮罩        猫形以外的透明区域会不会吃掉桌面的点击,以及遮罩面积是否和帧
                          自身的 alpha 占比吻合(高 DPI 下遮罩错位会在这里露馅)。
  5. 全局空闲检测          喝水/上厕所"是否真去做了"的判定依赖它。
  6. macOS 窗口属性        WA_MacAlwaysShowToolWindow 有没有设上(仅 darwin)。

**平台测不了的东西会标 SKIP,而 SKIP 不等于通过。** macOS 上的窗口失活、全屏浮层、托盘
点击语义、Retina 对齐这些只有肉眼能判断,自检末尾会打印一份核对清单。

用法:
    uv run python script/check_env.py [--hold]    源码树里跑
    drink-or-not --self-check [--hold]            打包产物里跑,同一套检查
"""

import json
import platform
import sys
import time

from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtGui import QBitmap, QPainter, QPixmap, QRegion
from PyQt5.QtWidgets import QApplication, QWidget

from .activity import IdleDetector
from .pet_window import apply_window_flags
from .resources import assets_dir

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
results = []


def report(status, title, detail=""):
    results.append((status, title))
    print(f"  [{status}] {title}" + (f"\n         {detail}" if detail else ""), flush=True)


def alpha_ratio(image):
    """image 里 alpha>0 的像素占比。跟 pet_window 的 setMask 用的判据一致。"""
    image = image.convertToFormat(image.Format_ARGB32)
    total = image.width() * image.height()
    if not total:
        return 0.0
    buf = image.constBits().asstring(image.sizeInBytes())
    stride = image.bytesPerLine()
    width_bytes = image.width() * 4
    opaque = 0
    for y in range(image.height()):
        row = buf[y * stride : y * stride + width_bytes]
        opaque += sum(1 for i in range(3, len(row), 4) if row[i])
    return opaque / float(total)


def build_mask_region(pixmap):
    """跟 pet_window 里一样的遮罩构造路径,顺手验证它不会抛。"""
    bitmap = QBitmap.fromImage(pixmap.toImage().createAlphaMask())
    return QRegion(bitmap)


class PetProbe(QWidget):
    """最小可用的宠物窗口,只为验证透明/定位/遮罩,不含任何业务逻辑。"""

    def __init__(self, frames):
        super().__init__()
        self.frames = frames
        self.drag_offset = QPoint()
        # 和真窗口共用同一份 flags:自检必须测真窗口的那套设置,不能各写各的
        apply_window_flags(self)
        self.resize(frames[0].size())
        self.setMask(build_mask_region(frames[0]))

        self._i = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._i = (self._i + 1) % len(self.frames)
        self.update()

    def paintEvent(self, _):
        QPainter(self).drawPixmap(0, 0, self.frames[self._i])

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag_offset = e.pos()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self.drag_offset)


def check_frames(assets):
    manifest_path = assets / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(
            f"assets 缺失:{manifest_path}\n"
            "  打包产物应当自带 assets(没带上就是打包漏了);\n"
            "  源码运行则先跑 script/prepare_assets.py 和 script/generate_frames.py。"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    idle = manifest["actions"]["idle"]
    frames = [QPixmap(str(assets / idle["dir"] / idle["pattern"].format(i))) for i in range(idle["count"])]
    blank = [i for i, f in enumerate(frames) if f.isNull()]
    if blank:
        report(FAIL, "动画帧加载", f"有 {len(blank)} 帧读不出来:{blank[:5]}")
    else:
        report(PASS, f"动画帧加载 {len(frames)} 帧 {frames[0].width()}x{frames[0].height()}")
    return frames


def check_platform(app):
    plugin = app.platformName()
    if sys.platform.startswith("linux"):
        if plugin != "xcb":
            report(FAIL, "窗口可自行定位", f"当前平台插件是 {plugin},move() 会被合成器忽略,宠物拖不动")
        else:
            report(PASS, "窗口可自行定位", f"平台插件 {plugin}")
        return
    if sys.platform == "darwin":
        # cocoa 是 macOS 上唯一能给出正确窗口层级和托盘的插件;xcb 意味着走了 XQuartz
        if plugin != "cocoa":
            report(
                FAIL,
                "平台插件不是 cocoa",
                f"当前是 {plugin}。macOS 上应当只有 cocoa;走 XQuartz(xcb)会让窗口层级、"
                "托盘、遮罩全部失真,先检查 QT_QPA_PLATFORM 是不是被外部设过。",
            )
        else:
            report(PASS, "平台插件 cocoa", "窗口可自行定位,层级/托盘行为由 cocoa 插件负责")
        return
    report(SKIP, "窗口可自行定位", f"{sys.platform}:没有针对该平台的判定规则,平台插件是 {plugin}")


def settle_move(app, win, target, timeout=0.8):
    """move() 在 X11 下是异步的:ConfigureNotify 回来之前 pos() 读到的还是旧值。

    只 processEvents() 一次会偶发读到旧位置,把"窗口定位"变成假 FAIL —— 自检的价值全在
    这个读数上,不能让它随机。轮询到位置落定或超时为止。
    """
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        if (win.pos() - target).manhattanLength() <= 2:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def check_window(app, win):
    win.show()
    app.processEvents()

    if win.testAttribute(Qt.WA_TranslucentBackground):
        report(PASS, "透明窗口属性已设置(是否真透明请看下面的猫)")
    else:
        report(FAIL, "透明窗口属性", "WA_TranslucentBackground 没设上")

    screen = app.primaryScreen().geometry()
    target = QPoint(
        max(0, screen.width() - win.width() - 60),
        max(0, screen.height() - win.height() - 120),
    )
    win.move(target)
    if settle_move(app, win, target):
        report(PASS, f"窗口定位 move({target.x()},{target.y()})")
    else:
        got = win.pos()
        report(FAIL, "窗口定位", f"要求 {target.x()},{target.y()},实际停在 {got.x()},{got.y()}")

    region = build_mask_region(win.frames[0])
    if region.isEmpty():
        report(FAIL, "点击遮罩", "从 alpha 得到的 QRegion 是空的")
        return
    covered = sum(r.width() * r.height() for r in region.rects())
    ratio = covered / float(win.width() * win.height())
    report(
        PASS,
        "点击遮罩已生效",
        f"{len(region.rects())} 个矩形,覆盖窗口 {ratio * 100:.0f}% 面积,其余区域点击穿透到桌面",
    )

    # 遮罩面积要和帧自身 alpha>0 的像素占比对得上。这条在高 DPI 下才有牙齿:
    # 如果 setMask 没把 devicePixelRatio 除掉,遮罩会整体放大,覆盖率随之跑偏。
    expected = alpha_ratio(win.frames[0].toImage())
    if abs(ratio - expected) <= 0.02:
        report(PASS, "遮罩与帧 alpha 吻合", f"遮罩 {ratio * 100:.1f}% vs 帧 {expected * 100:.1f}%")
    else:
        report(
            FAIL,
            "遮罩与帧 alpha 对不上",
            f"遮罩 {ratio * 100:.1f}%,帧 alpha 非零占比 {expected * 100:.1f}%,"
            f"devicePixelRatio={win.devicePixelRatioF()}。两者不该差这么多,"
            "多半是 setMask 没换算设备像素,点击区会整体错位。",
        )


def check_mac_window_flag(win):
    """darwin 专属:确认 WA_MacAlwaysShowToolWindow 真的设上了。

    注意这条只能证明属性设上了,不能证明 cocoa 插件读到了它 —— 后者要看猫在应用失活时
    会不会被藏起来,只能肉眼判断(见下面的清单)。
    """
    if sys.platform != "darwin":
        report(
            SKIP,
            "WA_MacAlwaysShowToolWindow",
            f"{sys.platform}:该属性只在 macOS 上有效,本平台设不设都一样",
        )
        return
    if win.testAttribute(Qt.WA_MacAlwaysShowToolWindow):
        report(
            PASS,
            "WA_MacAlwaysShowToolWindow 已设置",
            "属性设上了。但 cocoa 插件读没读到只能肉眼确认:点别的 App 让本进程失活,猫应当仍在屏幕上",
        )
    else:
        report(
            FAIL,
            "WA_MacAlwaysShowToolWindow 没设上",
            "应用失活时窗口会被系统藏起来,宠物会消失 —— 检查 pet_window.apply_window_flags 是否被调用",
        )


def check_screen_geometry(app):
    """纯读数,不判定。高 DPI / 多屏排错时第一时间要看的就是这几个值。"""
    screen = app.primaryScreen()
    geo = screen.geometry()
    avail = screen.availableGeometry()
    insets = (
        f"上 {avail.top() - geo.top()} 下 {geo.bottom() - avail.bottom()} "
        f"左 {avail.left() - geo.left()} 右 {geo.right() - avail.right()}"
    )
    print(
        f"  [INFO] 主屏 {geo.width()}x{geo.height()} @({geo.x()},{geo.y()}) "
        f"devicePixelRatio={screen.devicePixelRatio()} DPI={screen.logicalDotsPerInch():.0f}",
        flush=True,
    )
    print(
        f"  [INFO] 可用区 {avail.width()}x{avail.height()},被菜单栏/Dock 挤掉: {insets}",
        flush=True,
    )


EYEBALL_CHECKLIST = (
    "1. 切到别的 App 让本进程失活 -> 猫还在屏幕上吗?(WA_MacAlwaysShowToolWindow 是否真被 cocoa 读到)",
    "2. 用 Safari 之类进全屏 -> 猫还在吗?预期会消失(需要 NSWindowCollectionBehaviorCanJoinAllSpaces,本次未做)",
    "3. 左键点托盘图标 -> 菜单是不是也跟着弹出来了?(qcocoa 左键同时发 Trigger 且弹菜单)",
    "4. 把猫拖到屏幕最顶端 -> 还能拖动吗?菜单栏会不会吃掉点击?",
    "5. Dock 里有没有多出一个图标?(Qt.Tool 的 NSPanel 预期不进 Dock)",
    "6. 猫的边缘清晰吗?拖动时命中区跟手吗?(Retina 遮罩对齐)",
    "7. 把猫拖到另一块屏上 -> 位置对吗?重开应用后位置还在吗?",
)


def check_idle():
    print()
    detector = IdleDetector()
    if not detector.available:
        report(FAIL, "全局空闲检测", "没有任何可用来源,完成判定将始终记为未完成")
        return

    report(PASS, f"全局空闲检测: {detector.provider}", f"首次读数 {detector.idle_seconds():.2f}s")
    print("         接下来 6 秒每秒采一次 —— 期间别碰鼠标,数值应该往上涨:", flush=True)
    samples = []
    SECONDS = 6

    def after_samples():
        values = [v for v in samples if v is not None]
        if not values:
            report(FAIL, "空闲秒数读不出来", f"{detector.provider} 每次调用都返回 None")
        elif len(values) < len(samples):
            report(FAIL, "空闲秒数偶尔读不出来", f"{len(samples) - len(values)}/{len(samples)} 次返回 None")
        elif max(values) >= 1.0:
            report(PASS, "空闲秒数可信", f"峰值 {max(values):.2f}s,检测源确实在跟随真实输入")
        else:
            # 采样期间一直有输入事件在刷新空闲计时,这时"没涨"说明不了检测源有问题。
            # 这恰恰是坐在电脑前跑自检的常态,不能算 FAIL,否则每次都会误报。
            report(
                WARN,
                f"空闲秒数没涨(峰值 {max(values):.2f}s)",
                "采样期间一直有键鼠输入(你正坐在电脑前?)。请离开键鼠后再跑一次;\n"
                "         若那时数值仍然不涨,才是这个来源不可信,完成判定会失灵。",
            )

    def sample(i=0):
        value = detector.idle_seconds()
        samples.append(value)
        print(f"           {i + 1}. {'None' if value is None else format(value, '.2f') + 's'}", flush=True)
        if i >= SECONDS - 1:
            after_samples()
        else:
            QTimer.singleShot(1000, lambda: sample(i + 1))

    QTimer.singleShot(300, sample)


def main(notes, hold=False):
    print("=" * 64)
    print("drink_or_not 环境自检")
    print("=" * 64)
    print(f"Python {platform.python_version()} / {platform.platform()}")
    for n in notes:
        print(f"  · {n}")
    print()

    app = QApplication(sys.argv)
    print(f"  [INFO] Qt 实际使用的平台插件:{app.platformName()}")
    check_screen_geometry(app)
    print()

    check_platform(app)
    win = PetProbe(check_frames(assets_dir()))
    check_mac_window_flag(win)
    check_window(app, win)
    check_idle()

    print()
    print("=" * 64)
    if hold:
        print("猫会一直显示,关掉窗口或按 Ctrl-C 结束。")
    else:
        print("猫 8 秒后自动消失。重点看:猫周围是桌面壁纸,还是一块不透明的方块?")
    print("=" * 64)
    print()
    print("还有这些只能靠肉眼,自检判不了:")
    for line in EYEBALL_CHECKLIST:
        print(f"   {line}")

    if not hold:
        QTimer.singleShot(8000, app.quit)
    app.exec_()

    bad = [t for s, t in results if s == FAIL]
    warn = [t for s, t in results if s == WARN]
    skip = [t for s, t in results if s == SKIP]
    ok = len(results) - len(bad) - len(warn) - len(skip)
    print()
    if bad:
        print(f"自检结束:{len(bad)} 项 FAIL -> " + ";".join(bad))
    else:
        print(f"自检结束:{ok} 项通过")
    if warn:
        print(f"另有 {len(warn)} 项 WARN -> " + ";".join(warn))
    if skip:
        # 明确单列:SKIP 不等于通过,不能混进"通过"里凑数
        print(f"另有 {len(skip)} 项 SKIP(本平台测不了,不代表没问题)-> " + ";".join(skip))
    if skip or sys.platform == "darwin":
        print("别忘了把上面那份肉眼清单过一遍 —— SKIP 掉的正是那些。")
    return 1 if bad else 0
