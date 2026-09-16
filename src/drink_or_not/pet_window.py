"""宠物窗口:无边框、透明、置顶,自己画猫和气泡。

窗口布局从上到下是 [气泡区][猫的画布]。气泡区常驻透明,平时靠 setMask 排除在
点击区域之外,所以不会挡住底下的桌面图标;气泡显示时再把它的矩形并进同一个 mask。

setMask 用的是 createAlphaMask(),它把 alpha>0 的像素全部算进来(实测遮罩覆盖
窗口 32% 面积,恰好等于图像 alpha 非零像素的占比),所以抗锯齿的边缘不会被裁掉,
不需要额外膨胀。
"""

import json
import logging
from typing import List, Optional

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBitmap, QPainter, QPixmap, QRegion
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from . import messages
from .bubble import Bubble
from .resources import assets_dir

log = logging.getLogger(__name__)

BUBBLE_AREA_H = 150  # 气泡区常驻高度,不随宠物缩放,免得缩小后字看不清
BUBBLE_MIN_W = 300  # 窗口最小宽度,保证长句子不会被挤成一列
EDGE_MARGIN = 60  # 首次启动时离屏幕边缘的距离


class SpriteSet:
    """一组动画帧。"""

    def __init__(self, frames: List[QPixmap], fps: int, canvas: QSize, bbox: QRect):
        self.frames = frames
        self.fps = fps
        self.canvas = canvas
        self.bbox = bbox

    @classmethod
    def load(cls, scale: float) -> "SpriteSet":
        base = assets_dir()
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        idle = manifest["actions"]["idle"]
        size = QSize(*manifest["canvas"])
        target = QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))

        frames = []
        for i in range(idle["count"]):
            path = base / idle["dir"] / idle["pattern"].format(i)
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                raise RuntimeError(f"动画帧读不出来:{path}")
            frames.append(pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        bbox = QRect(*manifest["bbox"])
        scaled_bbox = QRect(
            round(bbox.x() * scale),
            round(bbox.y() * scale),
            round(bbox.width() * scale),
            round(bbox.height() * scale),
        )
        return cls(frames, idle["fps"], frames[0].size(), scaled_bbox)


class PetWindow(QWidget):
    settings_requested = pyqtSignal()
    help_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    test_requested = pyqtSignal(str)
    bubble_action = pyqtSignal(str, str)  # (kind, 按钮文字)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.sprites = SpriteSet.load(cfg["pet"]["scale"])
        self.bubble = Bubble()
        self.current_kind = ""
        self._frame = 0
        self._drag_offset = QPoint()
        self._dragging = False
        self._cat_origin = QPoint()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("drink_or_not")

        self._relayout()
        self._build_bubble_region()
        self._apply_mask()
        self.restore_position()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(max(16, 1000 // max(1, self.sprites.fps)))

        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self.hide_bubble)

    # ---------- 布局 ----------

    def _relayout(self) -> None:
        canvas = self.sprites.canvas
        self.win_w = max(canvas.width(), BUBBLE_MIN_W)
        self.win_h = BUBBLE_AREA_H + canvas.height()
        self._cat_origin = QPoint((self.win_w - canvas.width()) // 2, BUBBLE_AREA_H)
        self.resize(self.win_w, self.win_h)
        self._bubble_area = QRect(0, 0, self.win_w, BUBBLE_AREA_H)

    def _build_bubble_region(self) -> None:
        """所有帧 alpha 的并集,平移到猫在窗口里的位置。"""
        region = QRegion()
        for pixmap in self.sprites.frames:
            region = region.united(QRegion(QBitmap.fromImage(pixmap.toImage().createAlphaMask())))
        self._cat_region = region.translated(self._cat_origin.x(), self._cat_origin.y())

    def _apply_mask(self) -> None:
        if self.cfg["pet"]["click_region"] == "rect":
            self.clearMask()
            return
        region = QRegion(self._cat_region)
        if self.bubble.visible and not self.bubble.body.isEmpty():
            region = region.united(QRegion(self.bubble.body.adjusted(0, 0, 0, 10)))
        self.setMask(region)

    # ---------- 动画 ----------

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % len(self.sprites.frames)
        self.update(self._cat_origin.x(), self._cat_origin.y(), self.sprites.canvas.width(), self.sprites.canvas.height())

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.drawPixmap(self._cat_origin, self.sprites.frames[self._frame])
        self.bubble.paint(painter)

    # ---------- 位置 ----------

    def default_position(self) -> QPoint:
        area = QApplication.primaryScreen().availableGeometry()
        return QPoint(area.right() - self.win_w - EDGE_MARGIN, area.bottom() - self.win_h - EDGE_MARGIN)

    def _on_screen(self, pos: QPoint) -> bool:
        """窗口左上角附近得真的落在某块屏幕的可用区里。"""
        probe = QRect(pos + QPoint(24, 24), QSize(1, 1))
        return any(s.availableGeometry().contains(probe) for s in QApplication.screens())

    def restore_position(self) -> None:
        saved = self.cfg["pet"].get("pos")
        pos = QPoint(*saved) if saved else None
        if pos is None or not self._on_screen(pos):
            if pos is not None:
                log.info("保存的位置 %s 不在任何现有屏幕上(换过显示器?),改放右下角", saved)
            pos = self.default_position()
        self.move(pos)

    def save_position(self) -> None:
        self.cfg["pet"]["pos"] = [self.pos().x(), self.pos().y()]

    # ---------- 气泡 ----------

    def show_bubble(
        self,
        kind: str,
        text: str,
        actions: tuple = ("知道了", "5 分钟后再提醒"),
        seconds: Optional[int] = None,
    ) -> None:
        self.current_kind = kind
        self.bubble.layout(self._bubble_area, text, actions, self._cat_origin.x() + self.sprites.canvas.width() // 2)
        self._apply_mask()
        self.update(self._bubble_area)
        self._bubble_timer.start(max(3, seconds or self.cfg["pet"]["bubble_seconds"]) * 1000)

    def hide_bubble(self) -> None:
        if not self.bubble.visible:
            return
        self.bubble.visible = False
        self.bubble.buttons = []
        self._apply_mask()
        self.update(self._bubble_area)

    def refresh_bubble(self) -> None:
        """配置里的字号/文案变了以后重排。"""
        if self.bubble.visible:
            self.bubble.layout(self._bubble_area, self.bubble.text, tuple(b[0] for b in self.bubble.buttons), self._cat_origin.x() + self.sprites.canvas.width() // 2)

    # ---------- 交互 ----------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        label = self.bubble.button_at(event.pos())
        if label:
            self._bubble_timer.stop()
            kind = self.current_kind
            self.hide_bubble()
            self.bubble_action.emit(kind, label)
            return
        self._dragging = True
        self._drag_offset = event.pos()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.save_position()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction("设置…", self.settings_requested.emit)
        menu.addAction("帮助", self.help_requested.emit)
        menu.addSeparator()
        test = menu.addMenu("立即测试提醒")
        # 菜单文字里不放 emoji:Qt5 画不出彩色 emoji 字体,只会显示成空心方框
        for key in ("water", "toilet", "meal", "rest", "slack"):
            test.addAction(messages.TITLE[key], lambda k=key: self.test_requested.emit(k))
        test.addAction(messages.TITLE["daily_report"], lambda: self.test_requested.emit("daily_report"))
        test.addAction(messages.TITLE["startup"], lambda: self.test_requested.emit("startup"))
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        menu.exec_(event.globalPos())

    def apply_config(self, cfg: dict) -> None:
        """设置改完之后热应用:缩放进去了就得重算画布和遮罩。"""
        needs_relayout = cfg["pet"]["scale"] != self.cfg["pet"]["scale"]
        self.cfg = cfg
        if needs_relayout:
            self.sprites = SpriteSet.load(cfg["pet"]["scale"])
            self._frame = 0
            self._relayout()
            self._build_bubble_region()
            self.refresh_bubble()
        self._apply_mask()
        want_on_top = bool(cfg["pet"]["always_on_top"])
        if want_on_top != bool(self.windowFlags() & Qt.WindowStaysOnTopHint):
            was_visible = self.isVisible()
            if want_on_top:
                self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            else:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            # setWindowFlags 会把窗口藏起来,必须再 show 一次;但用户本来就是隐藏宠物的话
            # 不该因为改了设置就把它弹出来
            if was_visible:
                self.show()
