"""导入自己的形象、管理本地素材库。

转换是同步跑的(2048x2048 实测 1.3 秒,更大的图要更久),这期间主线程被占住。所以进度
框必须**先画出来**再开始干活,并在每一步回调里 processEvents 让它重绘。

不开 QThread 是因为抠图那几段纯 Python 循环(颜色距离、洪水填充、连通域标记)持有 GIL,
换个线程照样卡主线程,反而多出线程安全的坑。一秒多的等待用一个已经画好的模态框顶着就够了。
"""

import logging
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import sprite_convert, sprite_library

log = logging.getLogger(__name__)

IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)"
_ROLE_ID = Qt.UserRole
_ROLE_BUILTIN = Qt.UserRole + 1


class _ProgressDialog(QDialog):
    """转换期间顶着的模态框。故意关不掉:工作在主线程里,关掉也停不下来。"""

    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(320)
        self._label = QLabel("准备中…", self)
        self._label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    def step(self, text: str) -> None:
        self._label.setText(text)
        QApplication.processEvents()

    def reject(self) -> None:
        pass  # Esc 也关不掉


def import_flow(parent) -> Optional[str]:
    """选图 -> 转换 -> 自检 -> 落盘。返回新形象的 id;用户中途放弃返回 None。"""
    while True:
        path, _ = QFileDialog.getOpenFileName(parent, "选择形象图片", "", IMAGE_FILTER)
        if not path:
            return None
        name = Path(path).stem
        prepared = _convert(parent, path, name)
        if prepared is None:
            return None

        if prepared.problems:
            choice = _ask_problems(parent, prepared.problems)
            if choice == "retry":
                continue
            if choice == "abort":
                return None
            # "整图显示":不抠背景,整张图当形象。自检在这一趟没有意义。
            prepared = _convert(parent, path, name, whole=True)
            if prepared is None:
                return None

        try:
            info = sprite_library.install(prepared, name)
        except OSError as exc:
            log.exception("形象落盘失败")
            QMessageBox.critical(parent, "保存失败", f"写入素材库时出错:{exc}")
            return None
        return info.id


def manage_flow(parent) -> None:
    _ManageDialog(parent).exec_()


# ---------- 内部 ----------


def _convert(parent, path: str, name: str, *, whole: bool = False):
    box = _ProgressDialog(parent, "导入形象")
    box.step(f"正在读取 {name}…")
    box.show()
    QApplication.processEvents()

    prepared, error = None, None
    try:
        prepared = sprite_convert.prepare(path, whole=whole, progress=box.step)
    except sprite_convert.ConversionError as exc:
        error = str(exc)
    finally:
        box.close()

    if error is not None:
        QMessageBox.critical(parent, "导入失败", error)
    return prepared


def _ask_problems(parent, problems: List[str]) -> str:
    """返回 retry / whole / abort。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("抠图结果可能不对")
    box.setText("自动抠背景的结果看起来有问题:")
    box.setInformativeText("\n".join(f"· {p}" for p in problems))
    retry = box.addButton("重新选择图片", QMessageBox.AcceptRole)
    whole = box.addButton("整图显示", QMessageBox.ActionRole)
    box.addButton("放弃", QMessageBox.RejectRole)
    box.setDefaultButton(whole)
    box.exec_()

    chosen = box.clickedButton()
    if chosen is retry:
        return "retry"
    if chosen is whole:
        return "whole"
    return "abort"


class _ManageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理素材库")
        self.setMinimumWidth(400)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self._list = QListWidget(self)
        self._rename = QPushButton("重命名…", self)
        self._rename.clicked.connect(self._on_rename)
        self._delete = QPushButton("删除", self)
        self._delete.clicked.connect(self._on_delete)

        side = QVBoxLayout()
        side.addWidget(self._rename)
        side.addWidget(self._delete)
        side.addStretch(1)

        row = QHBoxLayout()
        row.addWidget(self._list, 1)
        row.addLayout(side)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("内置形象不能改名或删除。", self))
        layout.addLayout(row)
        layout.addWidget(buttons)

        self._list.currentItemChanged.connect(lambda *_: self._sync_buttons())
        self._reload()

    # ---------- 列表 ----------

    def _reload(self, keep: str = "") -> None:
        self._list.clear()
        for info in sprite_library.list_sprites():
            item = QListWidgetItem(info.name)
            item.setData(_ROLE_ID, info.id)
            item.setData(_ROLE_BUILTIN, info.builtin)
            self._list.addItem(item)
            if info.id == keep:
                self._list.setCurrentItem(item)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        self._sync_buttons()

    def _selected(self):
        item = self._list.currentItem()
        if item is None:
            return None, False
        return item.data(_ROLE_ID), bool(item.data(_ROLE_BUILTIN))

    def _sync_buttons(self) -> None:
        sprite_id, builtin = self._selected()
        editable = sprite_id is not None and not builtin
        self._rename.setEnabled(editable)
        self._delete.setEnabled(editable)

    # ---------- 动作 ----------

    def _on_rename(self) -> None:
        item = self._list.currentItem()
        sprite_id, builtin = self._selected()
        if sprite_id is None or builtin:
            return
        new_name, ok = QInputDialog.getText(self, "重命名形象", "新名字:", text=item.text())
        new_name = new_name.strip()
        if not ok or not new_name or new_name == item.text():
            return
        try:
            sprite_library.rename_sprite(sprite_id, new_name)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "重命名失败", str(exc))
            return
        self._reload(keep=sprite_id)

    def _on_delete(self) -> None:
        item = self._list.currentItem()
        sprite_id, builtin = self._selected()
        if sprite_id is None or builtin:
            return
        if QMessageBox.question(self, "删除形象", f"确定删除「{item.text()}」?删掉就找不回来了。") != QMessageBox.Yes:
            return
        try:
            sprite_library.delete_sprite(sprite_id)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self._reload()
