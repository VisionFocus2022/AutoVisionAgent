"""
语义分割引擎（segmentation_models_pytorch DeepLabV3+）— W3-T2 自兄弟树移植

Option A 轻量库：弃 mmseg/mmengine，改用 segmentation_models_pytorch（Apache-2.0）。
骨干默认 ResNet50，输出语义 mask [H, W]（类别索引）。

诚实回退：未装 smp → raise SupervisedEngineError（不返假数据）。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine
from models.supervised.device import resolve_device


@register_engine(TaskType.SSEG)
class SsegSmpEngine(AbstractTaskEngine):
    """segmentation_models_pytorch DeepLabV3+ 语义分割引擎。

    load → infer 出 [H, W] 语义图（类别索引）。
    """

    def __init__(self) -> None:
        super().__init__(TaskType.SSEG)
        # 默认架构参数（可被 checkpoint 内的 arch 覆盖）
        self._arch: str = "DeepLabV3Plus"
        self._encoder_name: str = "resnet50"
        self._num_classes: int = 2

    def load(self, weights_path: str, device: str = "cuda") -> None:
        """加载 smp 模型权重。

        checkpoint 可为：
        - 纯 state_dict（按默认 arch DeepLabV3Plus/resnet50 构造）
        - 含 'model' / 'state_dict' 键的 dict
        - 含 'arch' / 'encoder_name' / 'num_classes' 元信息的 dict
        """
        # W19（v3 第三波 FR-3.1）：cuda 不可用时诚实回退 cpu（lite 派生场景）
        device = resolve_device(device)
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        try:
            import segmentation_models_pytorch as smp
            import torch
        except ImportError as exc:
            raise SupervisedEngineError(
                f"segmentation_models_pytorch 未安装，无法加载语义分割模型: {exc}",
                task=self.task.value,
            ) from exc

        raw = self._safe_torch_load(weights_path, map_location="cpu")

        # 从 checkpoint 提取架构元信息（若有）
        if isinstance(raw, dict):
            self._arch = raw.get("arch", self._arch)
            self._encoder_name = raw.get("encoder_name", self._encoder_name)
            self._num_classes = raw.get("num_classes", self._num_classes)
            state = raw.get("state_dict") or raw.get("model") or raw
        else:
            state = raw

        # 构造 smp 模型
        try:
            model_cls = getattr(smp, self._arch)
        except AttributeError:
            model_cls = smp.DeepLabV3Plus
            self._arch = "DeepLabV3Plus"

        self._model = model_cls(
            encoder_name=self._encoder_name,
            encoder_weights=None,  # 不下载预训练权重，从 checkpoint 加载
            in_channels=3,
            classes=self._num_classes,
        )

        # 加载 state_dict
        try:
            self._model.load_state_dict(state, strict=False)
        except Exception as exc:
            raise SupervisedEngineError(
                f"加载 smp 权重失败: {exc}", task=self.task.value
            ) from exc

        self._model.eval()
        self._model.to(device)
        self._weights_path = weights_path
        self._device = device

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: Optional[list] = None,
    ) -> DetectionResult:
        """推理：图像 → 预处理 → 模型 → argmax → [H,W] 语义图。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)

        import numpy as np
        import torch

        arr = self._to_numpy(image)  # HxWx3 uint8
        h, w = arr.shape[:2]

        # 预处理：归一化 + NCHW
        tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).float() / 255.0
        # ImageNet 标准化
        mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        tensor = (tensor - mean) / std
        tensor = tensor.to(self._device)

        with torch.no_grad():
            out = self._model(tensor)  # [1, C, H', W']
            # 恢复到原始分辨率
            if out.shape[-2:] != (h, w):
                out = torch.nn.functional.interpolate(
                    out, size=(h, w), mode="bilinear", align_corners=False
                )
            pred = out.argmax(dim=1).squeeze(0).cpu()  # [H, W]

        return DetectionResult(
            task=TaskType.SSEG,
            masks=pred,
            labels=tuple(labels or [f"class_{i}" for i in range(self._num_classes)]),
        )

    @staticmethod
    def _to_numpy(image: Any) -> Any:
        import numpy as np
        if isinstance(image, str):
            from PIL import Image
            return np.asarray(Image.open(image).convert("RGB"))
        return np.asarray(image)


__all__ = ["SsegSmpEngine"]
