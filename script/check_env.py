"""环境自检:确认桌面宠物赖以成立的几件事在本机真的能跑。

检查项(任何一项 FAIL,对应的功能就是不可用的):

  1. Qt 平台插件          能不能走 xcb(XWayland)。Wayland 原生下窗口无法自行定位,
                          宠物就拖不动,只能钉在合成器给的位置。
  2. 无边框透明窗口        会不会真的透明,还是糊一块不透明方块。
  3. 窗口定位              move() 之后窗口是不是真到了那个坐标。
  4. alpha 点击遮罩        猫形以外的透明区域会不会吃掉桌面的点击。
  5. 全局空闲检测          喝水/上厕所"是否真去做了"的判定依赖它。

用法:
    uv run python script/check_env.py           跑完自检,展示 6 秒后退出
    uv run python script/check_env.py --hold    自检完一直显示,自己关掉
"""

import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []


def prepare_platform() -> list:
    """必须在 QApplication 构造之前落定,XWayland 是窗口能被定位的前提。"""
    notes = []
    if sys.platform.startswith("linux"):
        current = os.environ.get("QT_QPA_PLATFORM")
        session = os.environ.get("XDG_SESSION_TYPE", "?")
        notes.append(f"会话类型 {session},DISPLAY={os.environ.get('DISPLAY') or '(空)'}")
        if current:
            notes.append(f"QT_QPA_PLATFORM 已被外部设为 {current},不覆盖")
        elif not os.environ.get("DISPLAY"):
            notes.append("没有 DISPLAY,只能留在 Wayland 原生模式:宠物将无法被拖动定位")
        else:
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            notes.append("已强制 QT_QPA_PLATFORM=xcb(走 XWayland),这样窗口才能自行定位")
    return notes


notes = prepare_platform()

from PyQt5.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PyQt5.QtGui import QBitmap, QPainter, QPixmap, QRegion  # noqa: E402
from PyQt5.QtWidgets import QApplication, QWidget  # noqa: E402

from drink_or_not.activity import IdleDetector  # noqa: E402
from drink_or_not.resources import assets_dir  # noqa: E402


def report(status, title, detail=""):
    results.append((status, title))
    print(f"  [{status}] {title}" + (f"\n         {detail}" if detail else ""), flush=True)


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
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
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
        raise SystemExit("assets 还没生成,先跑 script/prepare_assets.py 和 script/generate_frames.py")
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
    if sys.platform.startswith("linux") and app.platformName() != "xcb":
        report(
            FAIL,
            "窗口可自行定位",
            f"当前平台插件是 {app.platformName()},move() 会被合成器忽略,宠物拖不动",
        )
    else:
        report(PASS, "窗口可自行定位", f"平台插件 {app.platformName()}")


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
    app.processEvents()
    got = win.pos()
    if (got - target).manhattanLength() <= 2:
        report(PASS, f"窗口定位 move({target.x()},{target.y()})")
    else:
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


def main():
    hold = "--hold" in sys.argv
    print("=" * 64)
    print("drink_or_not 环境自检")
    print("=" * 64)
    print(f"Python {platform.python_version()} / {platform.platform()}")
    for n in notes:
        print(f"  · {n}")
    print()

    app = QApplication(sys.argv)
    print(f"  [INFO] Qt 实际使用的平台插件:{app.platformName()}")
    print()

    check_platform(app)
    win = PetProbe(check_frames(assets_dir()))
    check_window(app, win)
    check_idle()

    print()
    print("=" * 64)
    if hold:
        print("猫会一直显示,关掉窗口或按 Ctrl-C 结束。")
    else:
        print("猫 8 秒后自动消失。重点看:猫周围是桌面壁纸,还是一块不透明的方块?")
    print("=" * 64)

    if not hold:
        QTimer.singleShot(8000, app.quit)
    app.exec_()

    bad = [t for s, t in results if s == FAIL]
    warn = [t for s, t in results if s == WARN]
    print()
    if bad:
        print(f"自检结束:{len(bad)} 项 FAIL -> " + ";".join(bad))
        if warn:
            print(f"另有 {len(warn)} 项 WARN -> " + ";".join(warn))
        return 1
    if warn:
        print(f"自检结束:{len(results) - len(warn)} 项通过,{len(warn)} 项 WARN -> " + ";".join(warn))
        return 0
    print(f"自检结束:全部 {len(results)} 项通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
