"""
语义分割引擎（mmsegmentation DeepLabV3+）— FR-A6

mmseg >= 1.2.0，使用 DeepLabV3+/ResNet50-V1c 骨干。
输出语义 mask [H, W]（类别索引）。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine


@register_engine(TaskType.SSEG)
class SsegMmsegEngine(AbstractTaskEngine):
    """mmseg DeepLabV3+ 语义分割引擎。"""

    def __init__(self) -> None:
        super().__init__(TaskType.SSEG)

    def load(self, weights_path: str, device: str = "cuda") -> None:
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        try:
            from mmengine.config import Config
            from mmengine.runner import load_checkpoint
            from mmseg.models import build_segmentor

            cfg = Config.fromfile(weights_path.replace(".pth", ".py")
                                  if weights_path.endswith(".pth")
                                  else weights_path)
            self._model = build_segmentor(cfg.model)
            load_checkpoint(self._model, weights_path, map_location="cpu")
            self._model.eval()
            self._model.to(device)
        except ImportError:
            # mmseg 未安装时回退到纯 torch 加载（测试桩）
            self._model = self._safe_torch_load(weights_path, map_location="cpu")
        except Exception as exc:
            raise SupervisedEngineError(
                f"加载语义分割模型失败: {exc}", task=self.task.value
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

        import torch

        arr = self._to_numpy(image)
        # mmseg 推理：模型接收 metainfo 格式
        if hasattr(self._model, "inference"):
            result = self._model.inference(arr[..., ::-1], batch_size=1)
            pred = result[0].pred_sem_seg.data.cpu().numpy()
        else:
            # 纯 torch 回退路径
            tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).float() / 255.0
            tensor = tensor.to(self._device)
            with torch.no_grad():
                out = self._model(tensor)
                if isinstance(out, dict):
                    pred = out.get("sem_seg", list(out.values())[0]).cpu().numpy()
                else:
                    pred = out.argmax(dim=1).squeeze(0).cpu().numpy()

        return DetectionResult(
            task=TaskType.SSEG,
            masks=torch.from_numpy(pred),
            labels=tuple(labels or ["background", "defect"]),
        )


__all__ = ["SsegMmsegEngine"]
