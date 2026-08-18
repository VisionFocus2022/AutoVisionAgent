"""
关键点检测引擎（YOLOv8-Pose）— FR-A5

输出 [N, K, 3] 关键点张量（x, y, confidence）。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine
from models.supervised.device import resolve_device


@register_engine(TaskType.POSE)
class PoseYoloEngine(AbstractTaskEngine):
    """YOLOv8-Pose 关键点检测引擎。"""

    def __init__(self) -> None:
        super().__init__(TaskType.POSE)

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
        if r.keypoints is None or len(r.keypoints) == 0:
            return DetectionResult(task=TaskType.POSE)

        kpts = r.keypoints.data  # [N, K, 3] — x, y, conf
        xyxy = r.boxes.xyxy.cpu().numpy() if r.boxes is not None else None
        conf = r.boxes.conf.cpu().numpy() if r.boxes is not None else None
        # W10-T3 修复：标签须按类别 id（cls）映射，并对短标签表越界回退 person_i
        # （修复前误用 int(conf)——置信度取整恒为 0，labels 永远映射到 labels[0]）
        cls = r.boxes.cls.cpu().numpy() if r.boxes is not None else None

        return DetectionResult(
            task=TaskType.POSE,
            boxes=tuple(tuple(float(v) for v in row) for row in xyxy) if xyxy is not None else (),
            scores=tuple(float(c) for c in conf) if conf is not None else (),
            labels=tuple(
                labels[int(k)] if labels and int(k) < len(labels)
                else f"person_{i}"
                for i, k in enumerate(cls)
            ) if cls is not None else (),
            keypoints=kpts.cpu(),
        )


__all__ = ["PoseYoloEngine"]
