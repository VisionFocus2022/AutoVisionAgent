"""画笔标注模式（快捷键 P）。

左键按下连续移动 → 沿路径收集点 → 释放完成。
"""
from __future__ import annotations

from typing import Optional

from labeling.base import AnnotationMode, DEFAULT_COLOR, RGBA, Point, Shape
from labeling.geometry import simplify_polyline
from labeling.modes._base import AbstractLabeler


class BrushLabeler(AbstractLabeler):
    """画笔标注器。

    交互流程：
    1. on_press(pt) — 左键按下开始画笔路径
    2. on_move(pt) — 持续拖拽追加路径点
    3. on_release(pt) — 释放完成，经 Douglas-Peucker 简化后构建多边形

    Args:
        brush_size: 画笔粗细（像素，仅影响渲染，不影响数据）。
        simplify_epsilon: 轮廓简化容差。
    """

    mode = AnnotationMode.BRUSH

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        brush_size: int = 3,
        simplify_epsilon: float = 2.0,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=2)
        self._brush_size = brush_size
        self._simplify_epsilon = simplify_epsilon

    def on_press(self, pt: Point) -> None:
        self._active = True
        self._points.clear()
        self._points.append(pt)

    def on_move(self, pt: Point) -> None:
        if self._active:
            self._points.append(pt)
        self._cursor = pt

    def on_release(self, pt: Point) -> Optional[Shape]:
        if len(self._points) < 2:
            self.reset()
            return None
        # 简化路径；笔触须构成区域（≥3 点），完全共线的退化笔触丢弃
        simplified = simplify_polyline(
            list(self._points), self._simplify_epsilon
        )
        if len(simplified) < 3:
            self.reset()
            return None
        shape = self._build(tuple(simplified))
        self.reset()
        return shape

    @property
    def brush_size(self) -> int:
        return self._brush_size


__all__ = ["BrushLabeler"]
