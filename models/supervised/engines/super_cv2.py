"""
超分辨率引擎（cv2.dnn_superres）— FR-A9 / FR-G2 · T-FIX-1-03（W2 自兄弟树移植）

Option A 轻量库：弃 mmedit SR，改用 cv2.dnn_superres（OpenCV 自带）。
支持骨干：EDSR / ESPCN / FSRCNN / LapSRN（.pb 权重文件）。

诚实回退：无权重 → raise SupervisedEngineError（不返 INTER_NEAREST 放大的假数据）。
W2 适配：_to_numpy 走 imread_unicode（本树根路径含中文）。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from core.path_io import ascii_path_copy
from models.supervised import AbstractTaskEngine, register_engine


@register_engine(TaskType.SUPER)
class SuperCv2Engine(AbstractTaskEngine):
    """cv2.dnn_superres 超分辨率引擎（EDSR/ESPCN/FSRCNN/LapSRN）。

    load(weights.pb, model_name, scale) → infer(lr_image) → HR 图像。
    """

    def __init__(self) -> None:
        super().__init__(TaskType.SUPER)
        self._model_name: str = "edsr"
        self._scale: int = 4

    def load(
        self,
        weights_path: str,
        device: str = "cuda",
        model_name: str = "",
        scale: int = 0,
    ) -> None:
        """加载超分模型。

        Args:
            weights_path: .pb 权重文件路径（EDSR_x4.pb 等）。
            model_name: 模型名（edsr/espcn/fsrcnn/lapSRN），从文件名推断或显式指定。
            scale: 放大倍数（2/3/4），从文件名推断或显式指定。
        """
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        try:
            import cv2
        except ImportError as exc:
            raise SupervisedEngineError(
                f"opencv 未安装: {exc}", task=self.task.value
            ) from exc

        # 从文件名推断模型名和倍数
        fname = os.path.basename(weights_path).lower()
        if model_name:
            self._model_name = model_name.lower()
        elif "edsr" in fname:
            self._model_name = "edsr"
        elif "espcn" in fname:
            self._model_name = "espcn"
        elif "fsrcnn" in fname:
            self._model_name = "fsrcnn"
        elif "lapsrn" in fname:
            self._model_name = "lapsrn"

        if scale > 0:
            self._scale = scale
        else:
            # 从文件名提取倍数（如 EDSR_x4.pb → 4）
            import re
            m = re.search(r"x?(\d+)", fname)
            if m:
                self._scale = int(m.group(1))

        try:
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            # cv2.dnn ReadProtoFromBinaryFile 在 Windows 走窄字符文件 API，中文路径静默崩；
            # 用 ascii_path_copy 把非 ASCII 路径拷成 ASCII 名临时文件喂给 readModel。
            with ascii_path_copy(weights_path) as (ascii_weights_path, _):
                sr.readModel(ascii_weights_path)
                # 选择后端（CUDA 优先，CPU 回退）
                try:
                    sr.setModel(self._model_name, self._scale)
                except cv2.error:
                    # 某些 OpenCV 版本模型名大小写敏感
                    sr.setModel(self._model_name.capitalize(), self._scale)
            self._model = sr
        except Exception as exc:
            raise SupervisedEngineError(
                f"加载超分模型失败: {exc}", task=self.task.value
            ) from exc

        self._weights_path = weights_path
        self._device = device

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: Optional[list] = None,
    ) -> DetectionResult:
        """超分推理：LR 图像 → dnn_superres → HR 图像。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)

        import cv2

        arr = self._to_numpy(image)
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)

        # 真超分推理
        hr = self._model.upsample(arr)

        return DetectionResult(
            task=TaskType.SUPER,
            score=1.0,
            labels=("super_resolved",),
        ).with_extra("hr_image", hr)

    @property
    def scale(self) -> int:
        """当前放大倍数。"""
        return self._scale

    @property
    def model_name(self) -> str:
        """当前骨干模型名。"""
        return self._model_name

    @staticmethod
    def _to_numpy(image: Any) -> Any:
        import numpy as np

        if isinstance(image, str):
            from core.image_io import imread_unicode
            return imread_unicode(image)
        return np.asarray(image)


__all__ = ["SuperCv2Engine"]
