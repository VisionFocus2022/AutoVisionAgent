"""YOLOv8-Seg 实例分割引擎基类（TD-01 去重；W2 自兄弟树移植）。

seg/pseg 共享 load/infer 逻辑，子类只覆写 task 与 mask 处理顺序。

去重前：seg_yolo.py（69 行）与 pseg_yolo.py（71 行）~95% 代码相同。
（W2 注：本树 pseg_yolo 暂保持独立实现，去重重构不在本波范围。）
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine


class _YoloSegBase(AbstractTaskEngine):
    """YOLOv8-Seg 实例分割共享基类。

    子类设置 self.task 并可选覆写 _process_results()。
    """

    def __init__(self, task: TaskType) -> None:
        super().__init__(task)

    def load(self, weights_path: str, device: str = "cuda") -> None:
        """加载 YOLOv8-Seg 权重。"""
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
        """执行实例分割，返回每个实例的 bbox + 二值 mask。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)

        results = self._model(image, conf=threshold, verbose=False)
        r = results[0]

        # 提取 mask（所有子类共享逻辑）
        masks_tensor = None
        if r.masks is not None and len(r.masks) > 0:
            masks_tensor = r.masks.data.cpu()  # [N,H,W]

        # 检查检测结果
        if r.boxes is None or len(r.boxes) == 0:
            return DetectionResult(
                task=self.task, boxes=(), scores=(), labels=(),
                masks=masks_tensor,
            )

        xyxy = r.boxes.xyxy.cpu().numpy()
        conf = r.boxes.conf.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy()

        return DetectionResult(
            task=self.task,
            boxes=tuple(tuple(float(v) for v in row) for row in xyxy),
            scores=tuple(float(c) for c in conf),
            labels=tuple(
                labels[int(c)] if labels and int(c) < len(labels)
                else f"defect_{int(c)}"
                for c in cls
            ),
            masks=masks_tensor,
        )


__all__ = ["_YoloSegBase"]
