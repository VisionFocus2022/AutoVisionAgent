"""
目标检测引擎（ultralytics YOLOv8）— FR-A2（W2 自兄弟树移植）

注意：ultralytics 为 AGPL-3.0 许可（R-5，已由项目决策接受）。
"""
from __future__ import annotations

import os
from typing import Any

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine
from models.supervised.device import resolve_device


@register_engine(TaskType.DET)
class DetYoloEngine(AbstractTaskEngine):
    """YOLOv8 检测引擎。"""

    def __init__(self) -> None:
        super().__init__(TaskType.DET)

    def load(self, weights_path: str, device: str = "cuda") -> None:
        """加载 YOLO 权重（.pt）。"""
        # W19（v3 第三波 FR-3.1）：cuda 不可用时诚实回退 cpu（lite 派生场景）
        device = resolve_device(device)
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        from ultralytics import YOLO

        self._model = YOLO(weights_path)
        self._weights_path = weights_path
        self._device = device

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: list | None = None,
    ) -> DetectionResult:
        """
        执行检测。

        Args:
            image: 图像路径(str)或 numpy 数组(HxWx3, uint8)。
            threshold: 置信度阈值。
            labels: 可选类别名列表（按类别索引映射）；未提供时标签为 ``defect_{cls}``。
        """
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)
        results = self._model(image, conf=threshold, verbose=False)
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return DetectionResult(task=TaskType.DET, boxes=(), scores=(), labels=())
        xyxy = r.boxes.xyxy.cpu().numpy()
        conf = r.boxes.conf.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy()
        return DetectionResult(
            task=TaskType.DET,
            boxes=tuple(tuple(float(v) for v in row) for row in xyxy),
            scores=tuple(float(c) for c in conf),
            labels=tuple(
                labels[int(c)] if labels and int(c) < len(labels)
                else f"defect_{int(c)}"
                for c in cls
            ),
        )


__all__ = ["DetYoloEngine"]
