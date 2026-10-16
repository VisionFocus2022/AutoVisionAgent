"""超分辨率任务路由引擎（TaskType.SUPER 唯一注册点）。

同一 SUPER 槽位现有两种后端，注册表每 TaskType 仅一工厂，故引入路由层：
按权重文件后缀分发——

- ``.pth`` / ``.pt`` → RealEsrganEngine（Real-ESRGAN，RRDBNet/SRVGGNet，
  官方 .pth 权重，GPU 优先）；
- ``.pb``           → SuperCv2Engine（cv2.dnn_superres，EDSR/ESPCN/
  FSRCNN/LapSRN）。

上层（VisionModelDispatcher / 预测页 / 视频超分）不感知后端差异，仍走
``get_engine(TaskType.SUPER)``；``infer`` 返回契约统一（extra["hr_image"]
为 HR 图像，BGR uint8）。super_cv2 不再自注册（其 @register_engine 已摘除，
类保留供路由与直连测试使用）。
"""
from __future__ import annotations

import os
from typing import Any

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine

_PTH_BACKEND_EXTS = (".pth", ".pt")


@register_engine(TaskType.SUPER)
class SuperRouterEngine(AbstractTaskEngine):
    """SUPER 任务路由：load 按权重后端选具体引擎，职责全委托。"""

    def __init__(self) -> None:
        super().__init__(TaskType.SUPER)
        self._backend: AbstractTaskEngine | None = None

    def load(
        self,
        weights_path: str,
        device: str = "cuda",
        **kwargs: Any,
    ) -> None:
        """按权重后缀加载（.pth/.pt → Real-ESRGAN；.pb → cv2.dnn_superres）。

        Raises:
            SupervisedEngineError: 后缀不支持，或后端引擎加载失败（透传）。
        """
        ext = os.path.splitext(str(weights_path))[1].lower()
        if ext in _PTH_BACKEND_EXTS:
            from models.supervised.engines.super_realesrgan import RealEsrganEngine

            backend: AbstractTaskEngine = RealEsrganEngine()
        elif ext == ".pb":
            from models.supervised.engines.super_cv2 import SuperCv2Engine

            backend = SuperCv2Engine()
        else:
            raise SupervisedEngineError(
                f"不支持的超分权重格式: '{ext}'（.pth/.pt → Real-ESRGAN；"
                f".pb → cv2.dnn_superres）",
                task=self.task.value,
            )
        backend.load(weights_path, device=device, **kwargs)
        self._backend = backend
        # 镜像后端元数据，供 dispatcher / GUI 直接读取
        self._model = getattr(backend, "_model", None)
        self._weights_path = str(weights_path)
        self._device = device

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: list | None = None,
    ) -> DetectionResult:
        """委托当前后端推理。"""
        if self._backend is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)
        return self._backend.infer(image, threshold=threshold, labels=labels)

    def unload(self) -> None:
        """释放后端资源并清路由态。"""
        if self._backend is not None:
            self._backend.unload()
            self._backend = None
        self._model = None
        self._weights_path = ""

    # ---- 元数据透传 ----

    @property
    def backend_name(self) -> str:
        """当前后端引擎类名（未加载时为空串）。"""
        return type(self._backend).__name__ if self._backend else ""

    @property
    def scale(self) -> int:
        """当前放大倍数（透传后端；未加载报 0 由调用方预检）。"""
        return int(getattr(self._backend, "scale", 0))

    @property
    def model_name(self) -> str:
        """当前骨干模型名（透传后端）。"""
        return str(getattr(self._backend, "model_name", "") or "")


__all__ = ["SuperRouterEngine"]
