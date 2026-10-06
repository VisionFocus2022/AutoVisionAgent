"""多边形标注模式（快捷键 Q）。

左键逐点添加 → 右键/回车闭合多边形。
"""
from __future__ import annotations

from labeling.base import DEFAULT_COLOR, RGBA, AnnotationMode, Point, Shape
from labeling.geometry import close_polygon
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
        # L4（2026-10-06 三轮审查）：命中闭合区时直接提交而非静默吞点
        # ——此前 return 后既不加点也不闭合，用户以为"点击失灵"。
        # 现同步完成闭合提交（era-2 语义：commit 自动首尾相接）。
        # （旧 `pt[0] is not None` 对 float 恒真，属死代码已删。）
        if (
            len(self._points) >= 3
            and abs(pt[0] - self._points[0][0]) < self._close_threshold
            and abs(pt[1] - self._points[0][1]) < self._close_threshold
        ):
            self._close_requested = True  # 由 controller 的 commit 流程消费
            return
        self._points.append(pt)

    @property
    def close_requested(self) -> bool:
        """L4：用户已点击闭合区（controller 据此立即触发 commit）。"""
        return getattr(self, "_close_requested", False)

    def commit(self) -> Shape | None:
        if not self._can_commit():
            return None
        # era-2 语义：提交时自动闭合（首尾相接），状态随之清空
        shape = self._build(close_polygon(tuple(self._points)))
        self.reset()
        return shape

    def reset(self) -> None:
        """L4：连同闭合请求标志一并复位。"""
        self._close_requested = False
        super().reset()


__all__ = ["PolygonLabeler"]
