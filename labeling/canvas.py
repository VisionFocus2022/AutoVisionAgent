"""标注画布（QGraphicsScene 子类）。

管理 Shape 列表、撤销/重做栈、图像背景渲染。
"""
from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from labeling.base import DEFAULT_COLOR, AnnotationMode, Shape

_logger = logging.getLogger(__name__)


class AnnotationCanvas(QGraphicsScene):
    """标注画布场景。

    Signals:
        shapes_changed: shapes 列表变更时发射（参数：shapes 列表）。
        undo_redo_changed: 撤销/重做可用性变更时发射（can_undo, can_redo）。
    """

    shapes_changed = Signal(list)
    selection_changed = Signal(int)  # W55 编辑模式：选中形状索引；-1=取消
    undo_redo_changed = Signal(bool, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shapes: list[Shape] = []
        self._undo_stack: list[list[Shape]] = []
        self._redo_stack: list[list[Shape]] = []
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._show_shapes: bool = True
        self._image_pixmap: QPixmap | None = None
        self._selected_index: int | None = None

    # ============================== 图像管理 ============================== #
    @property
    def shapes(self) -> list[Shape]:
        """当前标注列表（只读视图）。"""
        return list(self._shapes)

    @property
    def image_size(self) -> tuple[int, int]:
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
        """保存当前状态到撤销栈（浅快照：era-2 契约，undo 恢复同一 Shape 对象）。"""
        self._undo_stack.append(list(self._shapes))
        self._redo_stack.clear()
        self._notify_undo_redo()

    def undo(self) -> bool:
        """撤销一步；返回是否真的执行（W1: 恢复 era-2 布尔契约）。"""
        if not self._undo_stack:
            return False
        self._redo_stack.append(list(self._shapes))
        self._shapes = self._undo_stack.pop()
        self._reset_selection()
        self._redraw()
        self._notify_undo_redo()
        self.shapes_changed.emit(self.shapes)
        return True

    def redo(self) -> bool:
        """重做一步；返回是否真的执行（W1: 恢复 era-2 布尔契约）。"""
        if not self._redo_stack:
            return False
        self._undo_stack.append(list(self._shapes))
        self._shapes = self._redo_stack.pop()
        self._reset_selection()
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
        mode=AnnotationMode.POLYGON,
        label: str = "",
        points: list | None = None,
        color=DEFAULT_COLOR,
    ) -> None:
        """添加标注形状。

        era-2 双契约：``mode`` 位既可传 Shape 实例（保持对象引用，供 undo
        身份语义），也可传 AnnotationMode 枚举 + label/points/color 组合
        （控制器/页面兼容路径）。
        """
        if isinstance(mode, Shape):
            shape = mode
        else:
            if points is None:
                points = []
            shape = Shape(
                mode=mode,
                points=tuple((float(p[0]), float(p[1])) for p in points),
                label=label,
                color=color,
            )
        self._save_state()
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
            self._reset_selection()
            self._redraw()
            self.shapes_changed.emit(self.shapes)

    def clear_shapes(self) -> None:
        """清空所有标注。"""
        if self._shapes:
            self._save_state()
            self._shapes.clear()
            self._reset_selection()
            self._redraw()
            self.shapes_changed.emit(self.shapes)

    def replace_all(self, shapes) -> None:
        """整体替换标注列表（era-2 契约：可撤销的单步替换）。"""
        new_shapes = list(shapes)
        self._save_state()
        self._shapes = new_shapes
        self._reset_selection()
        self._redraw()
        self.shapes_changed.emit(self.shapes)

    def set_items_visible(self, visible: bool) -> None:
        self._show_shapes = visible
        self._redraw()

    def itemsVisible(self) -> bool:
        return self._show_shapes

    def setItemsVisible(self, visible: bool) -> None:
        self.set_items_visible(visible)

    # ============================== W55 编辑模式：选中与顶点编辑 ============================== #

    @property
    def selected_index(self) -> int | None:
        """当前选中形状索引（None=未选中）。"""
        return self._selected_index

    def select_shape(self, index: int | None) -> None:
        """选中指定形状并绘制顶点手柄（None/越界=取消选中）。

        仅 POLYGON 形状显示手柄；其他类型可被选中但不渲染手柄，
        编辑操作（move/insert/remove_vertex）对其一律拒绝。
        """
        idx = (
            index
            if index is not None and 0 <= index < len(self._shapes)
            else None
        )
        if idx == self._selected_index:
            return
        self._selected_index = idx
        self._redraw()
        self.selection_changed.emit(idx if idx is not None else -1)

    def clear_selection(self) -> None:
        """取消选中（不产生 undo 步）。"""
        self.select_shape(None)

    def _reset_selection(self) -> None:
        """列表结构变化（undo/删除/清空/替换）后使选中索引失效。"""
        if self._selected_index is not None:
            self._selected_index = None
            self.selection_changed.emit(-1)

    def _editable_polygon(self) -> tuple[int, Shape] | None:
        """当前选中且为可编辑 POLYGON 的 (索引, 形状)；否则 None。"""
        idx = self._selected_index
        if idx is None or not 0 <= idx < len(self._shapes):
            return None
        shape = self._shapes[idx]
        if shape.mode is not AnnotationMode.POLYGON or len(shape.points) < 3:
            return None
        return idx, shape

    def begin_vertex_edit(self) -> None:
        """顶点编辑快照——拖动开始时调用，使一次拖动=一步 undo。"""
        self._save_state()

    def move_vertex(self, vertex_idx: int, pt) -> bool:
        """移动选中多边形顶点（拖动中调用；不发 shapes_changed）。

        闭合多边形（首尾同点）拖动首/尾顶点时同步另一份副本——
        收尾点只是渲染闭合约定，逻辑上是同一顶点，不同步会首尾分裂。
        """
        got = self._editable_polygon()
        if got is None:
            return False
        idx, shape = got
        pts = list(shape.points)
        if not 0 <= vertex_idx < len(pts):
            return False
        n = len(pts)
        # 闭合判定须在改点前（首点被改后与收尾副本必然不等）
        closed = n >= 4 and pts[0] == pts[-1]
        pts[vertex_idx] = (float(pt[0]), float(pt[1]))
        if closed:
            if vertex_idx == 0:
                pts[-1] = pts[0]
            elif vertex_idx == n - 1:
                pts[0] = pts[-1]
        self._replace_points(idx, pts)
        self._redraw()
        return True

    def insert_vertex(self, pos: int, pt) -> bool:
        """在选中多边形 pos 处插入顶点（一步 undo）。"""
        got = self._editable_polygon()
        if got is None:
            return False
        idx, shape = got
        pts = list(shape.points)
        pos = max(0, min(pos, len(pts)))
        pts.insert(pos, (float(pt[0]), float(pt[1])))
        self._save_state()
        self._replace_points(idx, pts)
        self._redraw()
        self.shapes_changed.emit(self.shapes)
        return True

    def remove_vertex(self, vertex_idx: int) -> bool:
        """删除选中多边形顶点（一步 undo）；删除后不足 3 点则拒绝。

        闭合多边形删除首/尾顶点=删同一逻辑顶点，两份副本一并移除
        （剩余须 ≥3 点：闭合 4 点三角形拒绝删端点）。
        """
        got = self._editable_polygon()
        if got is None:
            return False
        idx, shape = got
        pts = list(shape.points)
        if not 0 <= vertex_idx < len(pts):
            return False
        n = len(pts)
        closed = n >= 4 and pts[0] == pts[-1]
        if closed and vertex_idx in (0, n - 1):
            if n - 2 < 3:
                return False
            self._save_state()
            pts.pop(n - 1)
            pts.pop(0)
        else:
            if len(pts) <= 3:
                return False
            self._save_state()
            pts.pop(vertex_idx)
        self._replace_points(idx, pts)
        self._redraw()
        self.shapes_changed.emit(self.shapes)
        return True

    def _replace_points(self, idx: int, pts: list) -> None:
        """以新点列替换形状为**新对象**——undo 快照持旧引用，原位改会使
        撤销失效（era-2 浅快照契约：undo 恢复同一（旧）Shape 对象）。"""
        self._shapes[idx] = replace(self._shapes[idx], points=tuple(pts))

    # ============================== 渲染 ============================== #
    def _redraw(self) -> None:
        """重绘所有标注（先移除旧标注 items，再绘制新的）。"""
        # 移除已有的标注图形（保留 pixmap_item）
        for item in self.items():
            if item is not self._pixmap_item:
                self.removeItem(item)

        if not self._show_shapes:
            return

        for i, shape in enumerate(self._shapes):
            self._draw_shape(shape, selected=(i == self._selected_index))

    def _draw_shape(self, shape: Shape, selected: bool = False) -> None:
        """绘制单个标注（selected=True 时高亮描边并绘制顶点手柄）。"""
        color = QColor(*shape.color[:3], min(shape.color[3] if len(shape.color) > 3 else 255, 255))
        pen = QPen(color, 3 if selected else 2)
        if selected:
            pen.setColor(QColor(255, 200, 0))  # 选中高亮（琥珀）
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
            # 多边形/画笔 → QPolygonF（W14 P2-10：QPointF 静态导入，行为等价）
            poly = QPolygonF([QPointF(p[0], p[1]) for p in points])
            self.addPolygon(poly, pen, brush)
            if selected and shape.mode is AnnotationMode.POLYGON:
                # W55 顶点手柄：白边蓝心小方块，命中半径同 VERTEX_HIT_RADIUS 量级
                hp = QPen(QColor(255, 255, 255), 1)
                hb = QBrush(QColor(52, 152, 219, 255))
                for pt in points:
                    self.addRect(pt[0] - 3, pt[1] - 3, 6, 6, hp, hb)


__all__ = ["AnnotationCanvas"]
