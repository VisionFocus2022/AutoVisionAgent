"""
图像分类引擎（torchvision ResNet）— FR-A1

torchvision.models.resnet 系列，支持 1000 类 ImageNet 预训练或微调权重。
"""
from __future__ import annotations

import os
from typing import Any

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine
from models.supervised.device import resolve_device


@register_engine(TaskType.CLS)
class ClsTorchvisionEngine(AbstractTaskEngine):
    """torchvision 分类引擎（ResNet/EfficientNet）。"""

    def __init__(self) -> None:
        super().__init__(TaskType.CLS)
        self._transform = None

    def load(self, weights_path: str, device: str = "cuda") -> None:
        # W19（v3 第三波 FR-3.1）：cuda 不可用时诚实回退 cpu（lite 派生场景）
        device = resolve_device(device)
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )

        self._model = self._safe_torch_load(weights_path, map_location="cpu")
        self._model.eval()
        self._model.to(device)
        self._weights_path = weights_path
        self._device = device
        # 预处理流水线一次性构建（避免每次推理重建）
        from torchvision import transforms
        self._transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
            ),
        ])

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: list | None = None,
    ) -> DetectionResult:
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)
        import torch

        arr = self._to_numpy(image)
        tensor = self._transform(arr).unsqueeze(0).to(self._device)
        with torch.no_grad():
            logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1)
            conf, pred = probs.max(dim=1)

        # W10-T3 修复：标签表短于类别数时回退 class_N（与 det/seg/pseg 的越界守卫对齐）
        pred_i = int(pred.item())
        label = labels[pred_i] if labels and pred_i < len(labels) else f"class_{pred_i}"
        return DetectionResult(
            task=TaskType.CLS,
            score=float(conf.item()),
            labels=(label,),
        )

    def infer_batch(
        self,
        images: list,
        threshold: float = 0.5,
        labels: list | None = None,
    ) -> list:
        """批量推理：将多张图像张量化后一次性前向传播。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)
        import torch

        tensors = [self._transform(self._to_numpy(img)) for img in images]
        batch = torch.stack(tensors).to(self._device)
        with torch.no_grad():
            logits = self._model(batch)
            probs = torch.softmax(logits, dim=1)
            confs, preds = probs.max(dim=1)

        results = []
        for i in range(len(images)):
            pred_i = int(preds[i].item())
            label = (
                labels[pred_i] if labels and pred_i < len(labels)
                else f"class_{pred_i}"
            )
            results.append(DetectionResult(
                task=TaskType.CLS,
                score=float(confs[i].item()),
                labels=(label,),
            ))
        return results


__all__ = ["ClsTorchvisionEngine"]
