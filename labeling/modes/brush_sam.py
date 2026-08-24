"""SAM 笔刷精修模式（快捷键 B，W44·B · 对标 SKolpha paint_to_shape）。

机制（取证报告 §6）：拖划笔划 → 采样为前景点提示（点距≥4px 稀疏化）
→ predict_points（多点 + 上轮 logits 作 mask_input 迭代精修）→
刷新 pending 多边形 → 双击/回车提交（提交后保留累积点与 logits，
可继续拖划细化；reset 全清）。v1 仅前景笔划（背景笔划需修饰键管道）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from labeling.base import (
    AnnotationMode,
    DEFAULT_COLOR,
    Point,
    RGBA,
    Shape,
)
from labeling.modes._base import AbstractLabeler

_logger = logging.getLogger(__name__)

# 笔划采样间距：相邻保留点最小像素距（防提示点爆炸）
_SAMPLE_MIN_PX = 4.0


class BrushSamLabeler(AbstractLabeler):
    """SAM 笔刷精修标注器：拖划=前景点累积 + mask_input 迭代。"""

    mode = AnnotationMode.SAM_BRUSH

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
        self._pending: Optional[Shape] = None
        self._stroke: list = []          # 当前笔划采样点
        self._fg_points: list = []       # 跨笔划累积前景提示
        self._logits: Any = None         # 上轮 logits（迭代输入）

    # ---- 外部注入 ---- #
    def set_adapter(self, adapter: Any) -> None:
        self._adapter = adapter

    def set_image(self, image: Any) -> None:
        self._image = image

    # ---- ILabeler 实现 ---- #
    def on_press(self, pt: Point) -> None:
        self._stroke = [pt]
        self._active = True

    def on_move(self, pt: Point) -> None:
        self._cursor = pt
        if self._stroke and _dist(self._stroke[-1], pt) >= _SAMPLE_MIN_PX:
            self._stroke.append(pt)

    def on_release(self, pt: Point) -> Optional[Shape]:
        if not self._stroke:
            self._active = False
            return None
        if _dist(self._stroke[-1], pt) >= _SAMPLE_MIN_PX:
            self._stroke.append(pt)
        stroke, self._stroke = self._stroke, []
        self._active = False
        if self._adapter is None or self._image is None:
            return None
        self._fg_points.extend(stroke)
        try:
            poly, logits = self._adapter.predict_points(
                self._image,
                list(self._fg_points),
                [1] * len(self._fg_points),
                mask_input=self._logits,
            )
        except Exception:  # noqa: BLE001 — SAM 推理异常不炸画布
            _logger.exception("SAM 笔刷精修预测失败")
            return None
        if len(poly) >= 3:
            self._pending = Shape(
                mode=AnnotationMode.POLYGON,
                points=tuple(poly),
                label=self.label,
                color=self._color,
            )
            self._logits = logits
        return None

    def preview(self) -> Optional[Shape]:
        return self._pending

    def commit(self) -> Optional[Shape]:
        """提交当前多边形（保留累积点与 logits，可继续细化）。"""
        shape = self._pending
        self._pending = None
        return shape

    def reset(self) -> None:
        super().reset()
        self._pending = None
        self._stroke = []
        self._fg_points = []
        self._logits = None


def _dist(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


__all__ = ["BrushSamLabeler"]
