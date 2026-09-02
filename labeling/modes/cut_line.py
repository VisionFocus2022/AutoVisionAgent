"""切割线标注模式（快捷键 C）。

左键逐点添加 → 右键/回车提交折线（≥2 点，不闭合）。

对标 SKolpha cut_line_label（W56 复刻；形态名锚点 @0x3d52001-0x3d5205b，
交互语义为推断级——实机核对后按 PRD AC-010 回填修订）。
"""
from __future__ import annotations

from labeling.base import DEFAULT_COLOR, RGBA, AnnotationMode, Point, Shape
from labeling.modes._base import AbstractLabeler


class CutLineLabeler(AbstractLabeler):
    """切割线标注器。

    交互流程：
    1. on_press(pt) — 左键单击添加折线顶点
    2. preview() — 返回含光标的进行中折线
    3. commit() — 回车/右键提交（至少 2 个点）

    与多边形的核心差异：点列不闭合（首尾不重合），画布渲染为虚线折线。
    """

    mode = AnnotationMode.CUT_LINE

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=2)

    def on_press(self, pt: Point) -> None:
        self._active = True
        self._points.append(pt)

    def commit(self) -> Shape | None:
        if not self._can_commit():
            return None
        shape = self._build(tuple(self._points))
        self.reset()
        return shape


__all__ = ["CutLineLabeler"]
