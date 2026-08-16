"""
超分辨率引擎（mmedit SR）— FR-A9 / FR-G2

将低分辨率图像放大为高分辨率（EDSR/RRDB/ESRGAN 骨干）。
对标 SKolpha 的 super 任务，提升微小缺陷可辨识度。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine


@register_engine(TaskType.SUPER)
class SuperMmeditEngine(AbstractTaskEngine):
    """mmedit 超分辨率引擎（EDSR/RRDB/ESRGAN）。"""

    def __init__(self) -> None:
        super().__init__(TaskType.SUPER)

    def load(self, weights_path: str, device: str = "cuda") -> None:
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        try:
            from mmedit.apis import init_model

            config_path = weights_path.replace(".pth", ".py")
            self._model = init_model(config_path, weights_path, device=device)
        except ImportError:
            self._model = self._safe_torch_load(weights_path, map_location="cpu")
        except Exception as exc:
            raise SupervisedEngineError(
                f"加载超分辨率模型失败: {exc}", task=self.task.value
            ) from exc

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

        import numpy as np

        arr = self._to_numpy(image)
        try:
            from mmedit.apis import restoration_inference

            output = restoration_inference(self._model, arr)
            if isinstance(output, dict):
                hr = output.get("output", list(output.values())[0])
            else:
                hr = output
            hr_np = (hr * 255).astype(np.uint8) if hasattr(hr, "max") and hr.max() <= 1.0 else np.asarray(hr, dtype=np.uint8)
        except ImportError:
            # 回退：最近邻放大 4x
            import cv2
            h, w = arr.shape[:2]
            hr_np = cv2.resize(arr, (w * 4, h * 4), interpolation=cv2.INTER_NEAREST)

        return DetectionResult(
            task=TaskType.SUPER,
            score=1.0,
            labels=("super_resolved",),
        ).with_extra("hr_image", hr_np)


__all__ = ["SuperMmeditEngine"]
