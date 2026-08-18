"""
异常检测引擎（anomalib PatchCore）— FR-A7（W2 自兄弟树移植，适配本树契约）

特点：PatchCore 属"先拟合后推理"范式——需在正常样本上拟合构建特征记忆库，
再对查询图打异常分。因此本引擎：
- ``load(weights_path)`` 加载已拟合的 anomalib checkpoint（.ckpt/.pt）。
- ``infer`` 运行异常评分（anomaly_map + 全局 score）。
- 真实拟合→推理的端到端验证随训练流水线进行；本处引擎层验证构造与错误路径。

W2 适配：本树 DetectionResult 无 anomaly_map 字段 → 存 ``extra["anomaly_map"]``；
score 为 None（模型未给出）时落 0.0。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine
from models.supervised.device import resolve_device


@register_engine(TaskType.ABDET)
class AbdetAnomalibEngine(AbstractTaskEngine):
    """anomalib PatchCore 异常检测引擎。"""

    def __init__(self) -> None:
        super().__init__(TaskType.ABDET)

    def load(self, weights_path: str, device: str = "cuda") -> None:
        """加载已拟合的 anomalib Patchcore checkpoint。"""
        # W19（v3 第三波 FR-3.1）：cuda 不可用时诚实回退 cpu（lite 派生场景）；
        # 归一必须在 load_from_checkpoint(map_location=) 之前生效
        device = resolve_device(device)
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        from anomalib.models import Patchcore

        try:
            # anomalib 2.x：Lightning 模块从 checkpoint 恢复
            self._model = Patchcore.load_from_checkpoint(weights_path, map_location=device)
        except Exception as exc:
            raise SupervisedEngineError(
                f"加载异常检测模型失败: {exc}", task=self.task.value
            ) from exc
        self._model.eval()
        self._weights_path = weights_path
        self._device = device

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: Optional[list] = None,
    ) -> DetectionResult:
        """
        执行异常评分。

        Args:
            image: 图像路径(str)或 numpy 数组(HxWx3, uint8)。
            threshold: 异常分数阈值（用于 is_defective 判定，记录到 extra）。
        """
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)
        import torch

        tensor = self._to_tensor(image, device=self._device)
        with torch.no_grad():
            out = self._model(tensor)
        anomaly_map = out.get("anomaly_map") if isinstance(out, dict) else getattr(out, "anomaly_map", None)
        score = out.get("pred_score") if isinstance(out, dict) else getattr(out, "pred_score", None)
        score_f = float(score.detach().cpu().mean()) if score is not None else None
        result = DetectionResult(
            task=TaskType.ABDET,
            score=score_f if score_f is not None else 0.0,
        )
        if anomaly_map is not None:
            result = result.with_extra("anomaly_map", anomaly_map)
        return result.with_extra(
            "is_defective", bool(score_f is not None and score_f >= threshold)
        )

    @staticmethod
    def _to_tensor(image: Any, device: str = "cpu") -> "Any":
        """将图像转为 [B,3,H,W] 归一化张量（anomalib 约定 [0,1]）。"""
        import numpy as np
        import torch

        if isinstance(image, str):
            from core.image_io import imread_unicode
            from PIL import Image

            arr = np.asarray(Image.open(image).convert("RGB"))
        elif isinstance(image, torch.Tensor):
            t = image.to(device)
            if t.dim() == 3:
                t = t.unsqueeze(0)
            return t.float() / (255.0 if t.max() > 1 else 1.0)
        else:
            arr = np.asarray(image)
        arr = arr[..., :3].astype("float32") / 255.0
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device)
        return t


__all__ = ["AbdetAnomalibEngine"]
