"""标注器抽象基类。

提供标注器公共状态管理和 Shape 构建，子类只需实现
on_press / on_move / on_release / preview / commit。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from labeling.base import (
    DEFAULT_COLOR,
    AnnotationMode,
    ILabeler,
    Point,
    RGBA,
    Shape,
)


class AbstractLabeler(ILabeler):
    """标注器基类（模板方法模式）。

    子类通过 self._points 管理当前形状的顶点列表，
    调用 self._build() 构建最终 Shape。

    Args:
        label: 缺陷/类别名。
        color: 描边色 RGBA。
        min_points: 完成标注所需的最少点数。
    """

    mode: AnnotationMode = AnnotationMode.POLYGON

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        min_points: int = 3,
    ) -> None:
        self.label: str = label
        self._color: RGBA = color
        self._min_points: int = min_points
        self._points: List[Point] = []
        self._cursor: Optional[Point] = None
        self._active: bool = False

    # ---- 公共辅助 ---- #
    @property
    def points(self) -> Tuple[Point, ...]:
        """当前顶点序列（只读副本；era-2 契约：commit 后为空元组）。"""
        return tuple(self._points)

    def _build(
        self, points: Optional[Tuple[Point, ...]] = None
    ) -> Shape:
        """构建 Shape 实例。"""
        pts = points if points is not None else tuple(self._points)
        return Shape(
            mode=self.mode,
            points=pts,
            label=self.label,
            color=self._color,
        )

    def _can_commit(self) -> bool:
        """检查是否满足提交条件（点数达标）。"""
        return len(self._points) >= self._min_points

    # ---- ILabeler 实现（子类覆写） ---- #
    def on_press(self, pt: Point) -> None:
        self._active = True
        self._points.append(pt)

    def on_move(self, pt: Point) -> None:
        self._cursor = pt

    def on_release(self, pt: Point) -> Optional[Shape]:
        return None

    def preview(self) -> Optional[Shape]:
        if not self._active or not self._points:
            return None
        pts = list(self._points)
        if self._cursor is not None:
            pts.append(self._cursor)
        return self._build(tuple(pts))

    def commit(self) -> Optional[Shape]:
        if not self._can_commit():
            return None
        shape = self._build()
        self.reset()
        return shape

    def reset(self) -> None:
        self._points.clear()
        self._cursor = None
        self._active = False


__all__ = ["AbstractLabeler"]
