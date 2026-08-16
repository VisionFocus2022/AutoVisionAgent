"""关键点标注模式（快捷键 K）。

左键单击放置关键点，每个关键点是一个独立的单点 Shape。
"""
from __future__ import annotations

from typing import Optional

from labeling.base import AnnotationMode, DEFAULT_COLOR, RGBA, Point, Shape
from labeling.modes._base import AbstractLabeler


class KeypointLabeler(AbstractLabeler):
    """关键点标注器。

    交互流程：
    1. on_press(pt) — 左键单击放置一个关键点（立即返回单点 Shape）
    2. on_release(pt) — 无操作（关键点在 press 时已完成）

    与其他模式不同，关键点每次点击即产出一个独立标注。
    """

    mode = AnnotationMode.KEYPOINT

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        keypoint_radius: float = 5.0,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=1)
        self._radius = keypoint_radius

    def on_press(self, pt: Point) -> None:
        """点击即放置关键点。"""
        self._active = True
        self._points = [pt]

    def on_release(self, pt: Point) -> Optional[Shape]:
        """释放返回单点标注。"""
        if not self._points:
            return None
        shape = self._build(tuple(self._points))
        self.reset()
        return shape

    @property
    def radius(self) -> float:
        return self._radius


__all__ = ["KeypointLabeler"]
