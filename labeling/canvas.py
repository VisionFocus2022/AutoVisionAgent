"""标注画布（QGraphicsScene 子类）。

管理 Shape 列表、撤销/重做栈、图像背景渲染。
"""
from __future__ import annotations

import copy
import logging
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem

from labeling.base import AnnotationMode, DEFAULT_COLOR, Shape

_logger = logging.getLogger(__name__)


class AnnotationCanvas(QGraphicsScene):
    """标注画布场景。

    Signals:
        shapes_changed: shapes 列表变更时发射（参数：shapes 列表）。
        undo_redo_changed: 撤销/重做可用性变更时发射（can_undo, can_redo）。
    """

    shapes_changed = Signal(list)
    undo_redo_changed = Signal(bool, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shapes: List[Shape] = []
        self._undo_stack: List[List[Shape]] = []
        self._redo_stack: List[List[Shape]] = []
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._show_shapes: bool = True
        self._image_pixmap: Optional[QPixmap] = None

    # ============================== 图像管理 ============================== #
    @property
    def shapes(self) -> List[Shape]:
        """当前标注列表（只读视图）。"""
        return list(self._shapes)

    @property
    def image_size(self) -> Tuple[int, int]:
        """返回 (width, height)，无图像时返回 (0, 0)。"""
        if self._image_pixmap and not self._image_pixmap.isNull():
            return (self._image_pixmap.width(), self._image_pixmap.height())
        return (0, 0)

    def set_image_pixmap(self, pm: QPixmap) -> None:
        """设置画布背景图像。"""
        self._image_pixmap = pm
        if self._pixmap_item is not None:
            self.removeItem(self._pixmap_item)
        self._pixmap_item = self.addPixmap(pm)
        self.setSceneRect(QRectF(pm.rect()))
        self.invalidate()

    def set_blank(self, w: int, h: int) -> None:
        """设置空白画布。"""
        pm = QPixmap(w, h)
        pm.fill(QColor(50, 50, 50))
        self.set_image_pixmap(pm)

    # ============================== 撤销/重做 ============================== #
    def _save_state(self) -> None:
        """保存当前状态到撤销栈。"""
        self._undo_stack.append(copy.deepcopy(self._shapes))
        self._redo_stack.clear()
        self._notify_undo_redo()

    def undo(self) -> bool:
        """撤销一步；返回是否真的执行（W1: 恢复 era-2 布尔契约）。"""
        if not self._undo_stack:
            return False
        self._redo_stack.append(copy.deepcopy(self._shapes))
        self._shapes = self._undo_stack.pop()
        self._redraw()
        self._notify_undo_redo()
        self.shapes_changed.emit(self.shapes)
        return True

    def redo(self) -> bool:
        """重做一步；返回是否真的执行（W1: 恢复 era-2 布尔契约）。"""
        if not self._redo_stack:
            return False
        self._undo_stack.append(copy.deepcopy(self._shapes))
        self._shapes = self._redo_stack.pop()
        self._redraw()
        self._notify_undo_redo()
        self.shapes_changed.emit(self.shapes)
        return True

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def _notify_undo_redo(self) -> None:
        self.undo_redo_changed.emit(self.can_undo(), self.can_redo())

    # ============================== Shape CRUD ============================== #
    def add_shape(
        self,
        mode: AnnotationMode = AnnotationMode.POLYGON,
        label: str = "",
        points: Optional[list] = None,
        color=DEFAULT_COLOR,
    ) -> None:
        """添加标注形状。"""
        if points is None:
            points = []
        self._save_state()
        shape = Shape(
            mode=mode,
            points=tuple((float(p[0]), float(p[1])) for p in points),
            label=label,
            color=color,
        )
        self._shapes.append(shape)
        self._redraw()
        self.shapes_changed.emit(self.shapes)

    def add_shape_from_points(
        self,
        points: list,
        mode: AnnotationMode = AnnotationMode.POLYGON,
        label: str = "",
    ) -> None:
        """从坐标点列表添加形状（兼容 paste 调用）。"""
        self.add_shape(mode=mode, label=label, points=points)

    def remove_shape_at(self, index: int) -> None:
        """删除指定索引的标注。"""
        if 0 <= index < len(self._shapes):
            self._save_state()
            self._shapes.pop(index)
            self._redraw()
            self.shapes_changed.emit(self.shapes)

    def clear_shapes(self) -> None:
        """清空所有标注。"""
        if self._shapes:
            self._save_state()
            self._shapes.clear()
            self._redraw()
            self.shapes_changed.emit(self.shapes)

    def set_items_visible(self, visible: bool) -> None:
        self._show_shapes = visible
        self._redraw()

    def itemsVisible(self) -> bool:
        return self._show_shapes

    def setItemsVisible(self, visible: bool) -> None:
        self.set_items_visible(visible)

    # ============================== 渲染 ============================== #
    def _redraw(self) -> None:
        """重绘所有标注（先移除旧标注 items，再绘制新的）。"""
        # 移除已有的标注图形（保留 pixmap_item）
        for item in self.items():
            if item is not self._pixmap_item:
                self.removeItem(item)

        if not self._show_shapes:
            return

        for shape in self._shapes:
            self._draw_shape(shape)

    def _draw_shape(self, shape: Shape) -> None:
        """绘制单个标注。"""
        color = QColor(*shape.color[:3], min(shape.color[3] if len(shape.color) > 3 else 255, 255))
        pen = QPen(color, 2)
        fill_color = QColor(color)
        fill_color.setAlpha(50)
        brush = QBrush(fill_color)

        points = shape.points
        if not points:
            return

        if shape.mode is AnnotationMode.RECTANGLE and len(points) >= 2:
            x1, y1 = points[0]
            x2, y2 = points[1]
            self.addRect(min(x1, x2), min(y1, y2),
                        abs(x2 - x1), abs(y2 - y1), pen, brush)
        elif shape.mode is AnnotationMode.KEYPOINT:
            for pt in points:
                self.addEllipse(pt[0] - 5, pt[1] - 5, 10, 10, pen, brush)
        else:
            # 多边形/画笔 → QPolygonF
            poly = QPolygonF([__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(p[0], p[1]) for p in points])
            self.addPolygon(poly, pen, brush)


__all__ = ["AnnotationCanvas"]
