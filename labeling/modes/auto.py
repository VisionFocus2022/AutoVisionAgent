"""AI 全自动预标注模式（快捷键 W，FR-C3）。

一键全图推理 → 批量产出 Shape。支持零样本 IDetector 或有监督引擎。

交互流程：
1. set_image(ndarray) 设置当前帧
2. on_press(任意位置) 或直接调 run() → 触发推理 → 缓存结果队列
3. commit() 逐个返回 Shape（控制器多次调用取完队列）
4. pending_count 可查剩余数量

detector 签名：Callable[[ndarray], List[Shape]]——
  零样本路径：封装 IDetector.detect → 转 Shape
  有监督路径：封装引擎 infer → 转 Shape
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from labeling.base import DEFAULT_COLOR, RGBA, AnnotationMode, Point, Shape
from labeling.modes._base import AbstractLabeler

# 检测器类型：image → Shape 列表
DetectorFn = Callable[[Any], list[Shape]]


class AutoLabeler(AbstractLabeler):
    """AI 全自动预标注器。

    Args:
        label: 缺陷/类别名。
        color: 描边色 RGBA。
        detector: 检测回调 (ndarray) → List[Shape]。
            若为 None，on_press/run 无操作。
        image: 当前帧 ndarray。
    """

    mode = AnnotationMode.AUTO

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        detector: DetectorFn | None = None,
        image: Any = None,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=0)
        self._detector: DetectorFn | None = detector
        self._image = image
        self._queue: list[Shape] = []

    # ---- 外部注入 ---- #
    def set_detector(self, detector: DetectorFn) -> None:
        """注入/替换检测回调。"""
        self._detector = detector

    def set_image(self, image: Any) -> None:
        """设置当前帧。"""
        self._image = image

    # ---- 批量推理 ---- #
    def run(self) -> int:
        """触发全图推理，返回检出的 Shape 数量。

        W55·v7 P2-4：失败返回 **-1** 哨兵（与零检出 0 区分——对齐 DET
        批量预标注「零检出/失败」分流的仓内先例）；两类结果均经反馈通道
        提示操作员（error/info）。
        W56·v7 P1-3：注入异步通道后返回 **-2**（受理中，结果经
        deliver("auto", shapes) 回投）；忙时返回 0（页面已提示）。
        """
        if self._detector is None or self._image is None:
            self._notify("warn", "SAM 未就绪（未加载权重或预热中）")
            return 0
        if self._async_channel is not None:
            if self._async_channel.submit(
                lambda: self._detector(self._image), "auto"
            ):
                return -2
            return 0
        try:
            shapes = self._detector(self._image)
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).exception("自动检测器推理失败")
            self._notify("error", f"SAM 自动检测失败: {exc}")
            return -1
        self._accept_shapes(shapes)
        return len(self._queue)

    def _accept_shapes(self, shapes) -> None:
        self._queue = list(shapes)
        self._active = True
        if not shapes:
            self._notify("info", "未检出目标")

    def deliver(self, tag: str, payload) -> None:
        """异步推理结果回投（主线程，W56·v7 P1-3；payload 为 Shape 列表）。"""
        if tag == "auto":
            self._accept_shapes(payload)

    @property
    def pending_count(self) -> int:
        """队列中待提交的 Shape 数。"""
        return len(self._queue)

    # ---- ILabeler 实现 ---- #
    def on_press(self, pt: Point) -> None:
        """点击触发全图推理（可视为「开始 AI 标注」按钮）。"""
        self.run()

    def on_move(self, pt: Point) -> None:
        self._cursor = pt

    def on_release(self, pt: Point) -> Shape | None:
        return None

    def preview(self) -> Shape | None:
        return None

    def commit(self) -> Shape | None:
        """逐个返回队列中的 Shape（控制器多次调用取完）。"""
        if self._queue:
            shape = self._queue.pop(0)
            return shape
        self._active = False
        return None

    def reset(self) -> None:
        super().reset()
        self._queue.clear()


__all__ = ["AutoLabeler"]
