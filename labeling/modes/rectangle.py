"""矩形标注模式（快捷键 R）。

左键按下拖拽 → 释放完成矩形。
"""
from __future__ import annotations

from typing import Optional

from labeling.base import AnnotationMode, DEFAULT_COLOR, RGBA, Point, Shape
from labeling.geometry import normalize_rectangle, rectangle_size
from labeling.modes._base import AbstractLabeler

# 误触保护阈值：任一边小于此值（像素）的矩形视为误触丢弃（era-2 语义）
MIN_SIZE: float = 2.0


class RectangleLabeler(AbstractLabeler):
    """矩形标注器。

    交互流程：
    1. on_press(pt) — 左键按下记录起点
    2. on_move(pt) — 拖拽实时更新终点（preview 显示矩形）
    3. on_release(pt) — 释放完成矩形（两个对角点）；误触小矩形丢弃
    """

    mode = AnnotationMode.RECTANGLE

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=2)

    def on_release(self, pt: Point) -> Optional[Shape]:
        if len(self._points) < 1:
            return None
        start = self._points[0]
        tl, br = normalize_rectangle(start, pt)
        w, h = rectangle_size(tl, br)
        if w < MIN_SIZE or h < MIN_SIZE:
            self.reset()
            return None
        shape = self._build((tl, br))
        self.reset()
        return shape

    def preview(self) -> Optional[Shape]:
        if not self._active or not self._points:
            return None
        start = self._points[0]
        end = self._cursor if self._cursor is not None else start
        tl, br = normalize_rectangle(start, end)
        return self._build((tl, br))


__all__ = ["RectangleLabeler"]
