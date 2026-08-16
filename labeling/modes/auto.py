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

from typing import Any, Callable, List, Optional

from labeling.base import AnnotationMode, DEFAULT_COLOR, RGBA, Point, Shape
from labeling.modes._base import AbstractLabeler

# 检测器类型：image → Shape 列表
DetectorFn = Callable[[Any], List[Shape]]


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
        detector: Optional[DetectorFn] = None,
        image: Any = None,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=0)
        self._detector: Optional[DetectorFn] = detector
        self._image = image
        self._queue: List[Shape] = []

    # ---- 外部注入 ---- #
    def set_detector(self, detector: DetectorFn) -> None:
        """注入/替换检测回调。"""
        self._detector = detector

    def set_image(self, image: Any) -> None:
        """设置当前帧。"""
        self._image = image

    # ---- 批量推理 ---- #
    def run(self) -> int:
        """触发全图推理，返回检出的 Shape 数量。"""
        if self._detector is None or self._image is None:
            return 0
        try:
            shapes = self._detector(self._image)
        except Exception:
            import logging as _log
            _log.getLogger(__name__).exception("自动检测器推理失败")
            return 0
        self._queue = shapes
        self._active = True
        return len(self._queue)

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

    def on_release(self, pt: Point) -> Optional[Shape]:
        return None

    def preview(self) -> Optional[Shape]:
        return None

    def commit(self) -> Optional[Shape]:
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
