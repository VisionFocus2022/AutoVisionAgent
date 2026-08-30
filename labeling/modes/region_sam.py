"""SAM 区域分割模式（快捷键 J，W43 · 对标 SKolpha rect_edit+ai_edit）。

机制（docs/skolpha-sam-annotation-forensics.md §4/§5）：
拖拽定/重设矩形区域 → 区域内单击 → SamAdapter.predict_point_in_box
（点+box 组合 prompt + 掩码∩矩形硬约束）→ pending 多边形 →
双击/回车提交。区域外单击忽略；未定区域单击忽略；reset 清区域。
SAM 未加载（adapter None）时单击无操作（诚实降级，同交互式）。
"""
from __future__ import annotations

import logging
from typing import Any

from labeling.base import (
    DEFAULT_COLOR,
    RGBA,
    AnnotationMode,
    Point,
    Shape,
)
from labeling.geometry import normalize_rectangle
from labeling.modes._base import AbstractLabeler

_logger = logging.getLogger(__name__)

# 拖拽判定阈值：位移低于此值视为单击（定区域 vs 分割的判别线）
_DRAG_MIN_PX = 5.0

# 区域矩形：归一化后的 (x1, y1, x2, y2)
Box = tuple[float, float, float, float]


class RegionSamLabeler(AbstractLabeler):
    """SAM 区域分割标注器：拖拽定区 → 区域内点击分割 → 提交多边形。

    Args:
        label: 缺陷/类别名。
        color: 描边色 RGBA。
        sam_adapter: SamAdapter 实例（需已 load + set_image）。
        image: 当前帧 ndarray（HxWx3）。
    """

    mode = AnnotationMode.REGION_SAM

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        sam_adapter: Any = None,
        image: Any = None,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=3)
        self._adapter = sam_adapter
        self._image = image
        self._pending: Shape | None = None
        self._box: Box | None = None
        self._press_start: Point | None = None

    # ---- 外部注入 ---- #
    def set_adapter(self, adapter: Any) -> None:
        self._adapter = adapter

    def set_image(self, image: Any) -> None:
        self._image = image

    @property
    def region(self) -> Box | None:
        """当前区域矩形（未定为 None）。"""
        return self._box

    # ---- ILabeler 实现 ---- #
    def on_press(self, pt: Point) -> None:
        self._press_start = pt
        self._active = True

    def on_move(self, pt: Point) -> None:
        self._cursor = pt

    def on_release(self, pt: Point) -> Shape | None:
        start = self._press_start
        self._press_start = None
        self._active = False
        if start is None:
            return None

        dist = ((pt[0] - start[0]) ** 2 + (pt[1] - start[1]) ** 2) ** 0.5
        if dist >= _DRAG_MIN_PX:
            # 拖拽：设/重设区域，丢弃旧 pending（区域变则旧分割失效）
            tl, br = normalize_rectangle(start, pt)
            self._box = (tl[0], tl[1], br[0], br[1])
            self._pending = None
            return None

        # 单击：区域内 → 分割；区域外/未定区域 → 忽略
        if self._box is None or self._adapter is None or self._image is None:
            return None
        x1, y1, x2, y2 = self._box
        if not (x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2):
            return None
        try:
            poly = self._adapter.predict_point_in_box(
                self._image, pt, self._box
            )
        except Exception:  # noqa: BLE001 — SAM 推理异常不炸画布
            _logger.exception("SAM 区域分割预测失败")
            return None
        if len(poly) >= 3:
            self._pending = Shape(
                mode=AnnotationMode.POLYGON,
                points=tuple(poly),
                label=self.label,
                color=self._color,
            )
        return None

    def preview(self) -> Shape | None:
        """pending 优先；拖拽/已定区域回矩形预览。"""
        if self._pending is not None:
            return self._pending
        rect: tuple[Point, Point] | None = None
        if self._press_start is not None:
            end = self._cursor if self._cursor is not None else self._press_start
            rect = normalize_rectangle(self._press_start, end)
        elif self._box is not None:
            rect = ((self._box[0], self._box[1]), (self._box[2], self._box[3]))
        if rect is None:
            return None
        return Shape(
            mode=AnnotationMode.RECTANGLE,
            points=(rect[0], rect[1]),
            label=self.label,
            color=self._color,
        )

    def commit(self) -> Shape | None:
        """确认当前分割多边形（双击/回车触发）。"""
        shape = self._pending
        self._pending = None
        return shape

    def reset(self) -> None:
        super().reset()
        self._pending = None
        self._box = None
        self._press_start = None


__all__ = ["RegionSamLabeler"]
