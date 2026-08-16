"""多边形标注模式（快捷键 Q）。

左键逐点添加 → 右键/回车闭合多边形。
"""
from __future__ import annotations

from typing import Optional

from labeling.base import AnnotationMode, DEFAULT_COLOR, RGBA, Point, Shape
from labeling.modes._base import AbstractLabeler


class PolygonLabeler(AbstractLabeler):
    """多边形标注器。

    交互流程：
    1. on_press(pt) — 左键单击添加顶点
    2. preview() — 返回含鼠标光标的进行中形状
    3. commit() — 回车/右键闭合多边形（至少 3 个点）
    """

    mode = AnnotationMode.POLYGON

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        close_threshold: float = 8.0,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=3)
        self._close_threshold = close_threshold

    def on_press(self, pt: Point) -> None:
        self._active = True
        # 检查是否点击起点闭合
        if (
            len(self._points) >= 3
            and pt[0] is not None
            and abs(pt[0] - self._points[0][0]) < self._close_threshold
            and abs(pt[1] - self._points[0][1]) < self._close_threshold
        ):
            return  # 不添加新点，等待 commit
        self._points.append(pt)

    def commit(self) -> Optional[Shape]:
        if not self._can_commit():
            return None
        shape = self._build()
        self.reset()
        return shape


__all__ = ["PolygonLabeler"]
