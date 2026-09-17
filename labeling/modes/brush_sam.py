"""SAM 笔刷精修模式（快捷键 B，W44·B · 对标 SKolpha paint_to_shape）。

机制（取证报告 §6）：拖划笔划 → 采样为前景点提示（点距≥4px 稀疏化）
→ predict_points（多点 + 上轮 logits 作 mask_input 迭代精修）→
刷新 pending 多边形 → 双击/回车提交（提交后保留累积点与 logits，
可继续拖划细化；reset 全清）。v1 仅前景笔划（背景笔划需修饰键管道）。
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
        self._pending: Shape | None = None
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

    def on_release(self, pt: Point) -> Shape | None:
        if not self._stroke:
            self._active = False
            return None
        if _dist(self._stroke[-1], pt) >= _SAMPLE_MIN_PX:
            self._stroke.append(pt)
        stroke, self._stroke = self._stroke, []
        self._active = False
        if self._adapter is None or self._image is None:
            # W55·v7 P2-4：未就绪不再静默吞笔划
            self._notify("warn", "SAM 未就绪（未加载权重或预热中）")
            return None
        self._fg_points.extend(stroke)
        if self._async_channel is not None:
            # W56·v7 P1-3：worker 线程推理；忙时页面已提示
            self._async_channel.submit(
                lambda: self._adapter.predict_points(
                    self._image,
                    list(self._fg_points),
                    [1] * len(self._fg_points),
                    mask_input=self._logits,
                ),
                "brush",
            )
            return None
        try:
            poly, logits = self._adapter.predict_points(
                self._image,
                list(self._fg_points),
                [1] * len(self._fg_points),
                mask_input=self._logits,
            )
        except Exception as exc:  # noqa: BLE001 — SAM 推理异常不炸画布
            _logger.exception("SAM 笔刷精修预测失败")
            self._notify("error", f"SAM 笔刷精修预测失败: {exc}")
            return None
        self._accept_result(poly, logits)
        return None

    def _accept_result(self, poly, logits) -> None:
        if len(poly) >= 3:
            self._pending = Shape(
                mode=AnnotationMode.POLYGON,
                points=tuple((float(p[0]), float(p[1])) for p in poly),
                label=self.label,
                color=self._color,
            )
            self._logits = logits

    def deliver(self, tag: str, payload) -> None:
        """异步推理结果回投（主线程，W56·v7 P1-3；payload=(poly, logits)）。"""
        if tag == "brush":
            poly, logits = payload
            self._accept_result(list(poly), logits)

    def preview(self) -> Shape | None:
        return self._pending

    def commit(self) -> Shape | None:
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
