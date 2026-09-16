"""猫头顶的对话气泡。

气泡和猫画在同一个窗口里,而不是另开一个窗口:宠物窗口本身在 Wayland/XWayland 下
定位就已经是最脆弱的一环,再挂一个跟随窗口只会多一份坐标系不同步的风险。代价是
窗口顶部要常驻一块透明区,靠 setMask 让它平时不接收点击(见 pet_window)。
"""

from typing import List, Optional, Tuple

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPainterPath, QPen, QRawFont

# 文案里带 emoji(💧🚽…)。Qt5 的字体回退不会自动找到彩色 emoji 字体,不单独处理就是一个个
# 空心方框。而把 emoji 字体塞进主字体的 fallback 列表又会坏事 —— Noto Color Emoji 连 ASCII
# 数字和空格都有自己的(很宽的)字形,一旦进了列表,QFontMetrics 就按它来算数字宽度,
# 于是"5 分钟"变成"5　　分钟"、设置里的 0.80 变成"0 . 8 0"。
# 所以这里不走字体的 fallback,改成把文本切成 emoji / 非 emoji 两段分别测宽和绘制。
EMOJI_FONTS = ("Noto Color Emoji", "Segoe UI Emoji", "Apple Color Emoji")
EMOJI_MIN_CODEPOINT = 0x2000  # 之下都是常规标点/数字/汉字,不值得让 emoji 字体插手

PAD = 14
LINE_GAP = 3
BTN_H = 26
BTN_GAP = 8
BTN_PAD_X = 12
TAIL_H = 10
TAIL_HALF_W = 9
RADIUS = 13

BG = QColor(255, 252, 245, 246)
BORDER = QColor(126, 116, 104, 150)
TEXT = QColor(58, 52, 46)
PRIMARY_BG = QColor(232, 104, 96)
PRIMARY_FG = QColor(255, 255, 255)
SECONDARY_BORDER = QColor(150, 140, 128, 190)
SECONDARY_FG = QColor(96, 88, 80)
SHADOW = QColor(0, 0, 0, 38)


def _find_emoji_font() -> Optional[QFont]:
    """系统里第一个能用的彩色 emoji 字体,没有就返回 None(那就退化成不显示 emoji 图形)。"""
    available = set(QFontDatabase().families())
    for name in EMOJI_FONTS:
        if name in available:
            return QFont(name)
    return None


class Bubble:
    """负责布局、绘制和按钮命中,不知道任何业务含义。"""

    def __init__(self, point_size: int = 11):
        self.font = QFont()
        self.font.setPointSize(point_size)
        self.button_font = QFont(self.font)
        self.button_font.setPointSize(max(8, point_size - 1))
        self.fm = QFontMetrics(self.font)
        self.btn_fm = QFontMetrics(self.button_font)

        self.emoji_font = _find_emoji_font()
        if self.emoji_font is not None:
            self.emoji_font.setPointSize(point_size)
            self.emoji_fm = QFontMetrics(self.emoji_font)
            self._emoji_raw = QRawFont.fromFont(self.emoji_font)
        else:
            self.emoji_fm = None
            self._emoji_raw = None

        self.visible = False
        self.text = ""
        self.body = QRect()
        self.buttons: List[Tuple[str, QRect]] = []

    # ---------- emoji 与正文混排 ----------

    def _is_emoji(self, ch: str) -> bool:
        if self._emoji_raw is None or ord(ch) < EMOJI_MIN_CODEPOINT:
            return False
        return self._emoji_raw.supportsCharacter(ord(ch))

    def _runs(self, text: str) -> List[Tuple[QFont, str]]:
        """切成 (字体, 片段) 的序列,相邻同类字符合并成一段。"""
        runs: List[Tuple[QFont, str]] = []
        for ch in text:
            font = self.emoji_font if self._is_emoji(ch) else self.font
            if runs and runs[-1][0] is font:
                runs[-1] = (font, runs[-1][1] + ch)
            else:
                runs.append((font, ch))
        return runs

    def _advance(self, text: str) -> int:
        total = 0
        for font, chunk in self._runs(text):
            metrics = self.emoji_fm if font is self.emoji_font else self.fm
            total += metrics.horizontalAdvance(chunk)
        return total

    def layout(self, area: QRect, text: str, buttons: Tuple[str, ...], tail_x: int) -> int:
        """按可用区域排好版,返回气泡占用的高度。"""
        self.text = text
        self.buttons = []
        self.visible = True

        line_h = self.fm.height() + LINE_GAP
        text_w = area.width() - 2 * PAD
        lines = self._wrap(text, text_w)

        content_w = max([self._advance(line) for line in lines] + [0])
        content_w = max(content_w, self._buttons_width(buttons))
        body_w = min(area.width(), content_w + 2 * PAD)
        body_h = PAD + len(lines) * line_h - LINE_GAP + BTN_GAP + BTN_H + PAD

        # 底部对齐并留出尾巴,尾巴尖指向猫头
        self.body = QRect(area.x() + (area.width() - body_w) // 2, area.bottom() - TAIL_H - body_h, body_w, body_h)
        self.tail_tip = QPoint(
            min(max(tail_x, self.body.left() + RADIUS + TAIL_HALF_W), self.body.right() - RADIUS - TAIL_HALF_W),
            self.body.bottom() + TAIL_H,
        )
        self._lines = lines
        self._layout_buttons(buttons)
        return body_h + TAIL_H

    def _wrap(self, text: str, width: int) -> List[str]:
        lines, current = [], ""
        for ch in text:
            if self._advance(current + ch) <= width or not current:
                current += ch
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
        return lines or [""]

    def _buttons_width(self, buttons: Tuple[str, ...]) -> int:
        if not buttons:
            return 0
        return sum(self.btn_fm.horizontalAdvance(b) + 2 * BTN_PAD_X for b in buttons) + BTN_GAP * (len(buttons) - 1)

    def _layout_buttons(self, buttons: Tuple[str, ...]) -> None:
        if not buttons:
            return
        widths = [self.btn_fm.horizontalAdvance(b) + 2 * BTN_PAD_X for b in buttons]
        total = sum(widths) + BTN_GAP * (len(buttons) - 1)
        x = self.body.x() + (self.body.width() - total) // 2
        y = self.body.bottom() - PAD - BTN_H
        for label, w in zip(buttons, widths):
            self.buttons.append((label, QRect(x, y, w, BTN_H)))
            x += w + BTN_GAP

    def button_at(self, pos: QPoint) -> Optional[str]:
        for label, rect in self.buttons:
            if rect.contains(pos):
                return label
        return None

    def paint(self, painter: QPainter) -> None:
        if not self.visible or self.body.isEmpty():
            return
        painter.setRenderHint(QPainter.Antialiasing, True)

        path = QPainterPath()
        path.addRoundedRect(float(self.body.x()), float(self.body.y()), float(self.body.width()), float(self.body.height()), RADIUS, RADIUS)
        path.moveTo(self.tail_tip.x() - TAIL_HALF_W, self.body.bottom() - 1)
        path.lineTo(self.tail_tip)
        path.lineTo(self.tail_tip.x() + TAIL_HALF_W, self.body.bottom() - 1)
        path.closeSubpath()

        painter.translate(0, 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(SHADOW)
        painter.drawPath(path)
        painter.translate(0, -2)

        painter.setBrush(BG)
        painter.setPen(QPen(BORDER, 1))
        painter.drawPath(path)

        painter.setPen(TEXT)
        y = self.body.y() + PAD + self.fm.ascent()
        for line in self._lines:
            x = self.body.x() + PAD
            for font, chunk in self._runs(line):
                painter.setFont(font)
                painter.drawText(x, y, chunk)
                metrics = self.emoji_fm if font is self.emoji_font else self.fm
                x += metrics.horizontalAdvance(chunk)
            y += self.fm.height() + LINE_GAP

        painter.setFont(self.button_font)
        for index, (label, rect) in enumerate(self.buttons):
            if index == 0:
                painter.setBrush(PRIMARY_BG)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(rect, 9, 9)
                painter.setPen(PRIMARY_FG)
            else:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(SECONDARY_BORDER, 1))
                painter.drawRoundedRect(rect, 9, 9)
                painter.setPen(SECONDARY_FG)
            painter.drawText(rect, Qt.AlignCenter, label)
