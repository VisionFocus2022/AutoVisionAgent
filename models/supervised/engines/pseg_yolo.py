"""
实例分割-Pro 引擎（YOLOv8-Seg 大模型变体）— FR-A4

对标 SKolpha 的 pseg 任务，使用 ultralytics yolov8x-seg。
输出 boxes + masks + labels。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine
from models.supervised.device import resolve_device


@register_engine(TaskType.PSEG)
class PsegYoloEngine(AbstractTaskEngine):
    """YOLOv8-Seg Pro 实例分割引擎。"""

    def __init__(self) -> None:
        super().__init__(TaskType.PSEG)

    def load(self, weights_path: str, device: str = "cuda") -> None:
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
        labels: Optional[list] = None,
    ) -> DetectionResult:
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)
        import torch

        results = self._model(image, conf=threshold, verbose=False)
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return DetectionResult(task=TaskType.PSEG)

        xyxy = r.boxes.xyxy.cpu().numpy()
        conf = r.boxes.conf.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy()

        masks = None
        if r.masks is not None and len(r.masks) > 0:
            masks = r.masks.data.cpu()  # [N, H, W]

        return DetectionResult(
            task=TaskType.PSEG,
            boxes=tuple(tuple(float(v) for v in row) for row in xyxy),
            scores=tuple(float(c) for c in conf),
            labels=tuple(
                labels[int(c)] if labels and int(c) < len(labels)
                else f"defect_{int(c)}"
                for c in cls
            ),
            masks=masks,
        )


__all__ = ["PsegYoloEngine"]
