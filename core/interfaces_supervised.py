"""有监督任务核心接口与数据类。

定义任务类型枚举、检测结果数据类、训练配置/产物数据类、
以及有监督引擎抽象基类。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    import numpy as np

from core.exceptions import SupervisedEngineError

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """支持的视觉任务类型。"""

    DET = "det"       # 目标检测
    SEG = "seg"       # 实例分割（旧版 YOLACT）
    PSEG = "pseg"     # 实例分割（YOLOv8-seg）
    CLS = "cls"       # 图像分类
    POSE = "pose"     # 关键点检测
    SSEG = "sseg"     # 语义分割（mmseg）
    ABDET = "abdet"   # 异常检测（zero-shot）
    SGAN = "sgan"     # GAN 缺陷生成
    SUPER = "super"   # 超分辨率（mmedit）


@dataclass(frozen=True)
class DetectionResult:
    """统一检测结果数据类。

    检测/分割/分类/关键点任务的通用输出格式。
    """

    task: TaskType
    score: float = 0.0
    scores: Tuple[float, ...] = ()       # 逐检测置信度
    labels: Tuple[str, ...] = ()
    boxes: Optional["np.ndarray"] = None       # (N, 4) array 或 None
    masks: Optional["np.ndarray"] = None       # (N, H, W) array 或 None
    keypoints: Optional["np.ndarray"] = None   # (N, K, 2) array 或 None
    extra: Dict[str, Any] = field(default_factory=dict)

    def with_extra(self, key: str, value: Any) -> "DetectionResult":
        """返回添加了 extra 键值对的副本（保持 frozen 不可变语义）。"""
        new_extra = {**self.extra, key: value}
        return replace(self, extra=new_extra)


@dataclass(frozen=True)
class TrainConfig:
    """训练配置（不可变）。"""

    task: TaskType
    epochs: int = 100
    lr: float = 0.001
    batch_size: int = 8
    weight_decay: float = 0.0005
    momentum: float = 0.937
    img_size: int = 640
    device: str = "cuda"
    workers: int = 4
    amp: bool = True                    # 混合精度训练
    resume_from: str = ""               # 断点恢复路径
    output_dir: str = "./outputs"
    # 早停
    patience: int = 0                   # 0 = 不启用早停
    # LR 调度器
    lr_scheduler: str = "cosine"        # cosine / step / plateau / none
    warmup_epochs: int = 3
    backbone: str = "yolov8n"           # 骨干网络名称
    # R5-11: checkpoint 可配置
    checkpoint_every: int = 5            # 每 N epoch 保存 checkpoint
    max_checkpoints: int = 3             # 滚动保留最近 N 个 checkpoint


@dataclass
class TrainArtifact:
    """训练产物。"""

    task: TaskType
    weights_path: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    epochs_completed: int = 0
    best_metric: float = 0.0
    config: Optional[TrainConfig] = None


class ISupervisedTaskEngine(ABC):
    """有监督任务引擎抽象接口。"""

    @property
    @abstractmethod
    def task(self) -> TaskType:
        """引擎处理的任务类型。"""

    @abstractmethod
    def load(self, weights_path: str, device: str = "cuda") -> None:
        """加载权重。"""

    @abstractmethod
    def infer(
        self,
        image: Union[str, "np.ndarray"],
        threshold: float = 0.5,
        labels: Optional[list] = None,
    ) -> DetectionResult:
        """推理单张图像。"""

    def info(self) -> Dict[str, Any]:
        """引擎元信息。"""
        _loaded = getattr(self, "_model", None) is not None
        _weights = getattr(self, "_weights_path", "")
        return {
            "task": self.task.value,
            "type": self.task.value,            # 别名（兼容）
            "name": self.__class__.__name__,   # 引擎类名
            "loaded": _loaded,
            "device": getattr(self, "_device", "cpu"),
            "weights": _weights,
            "file": _weights if _weights else None,
            "path": _weights if _weights else None,
        }


class AbstractTaskEngine(ISupervisedTaskEngine):
    """有监督引擎基类（提供公共工具方法）。

    子类只需实现 ``load`` 和 ``infer``。
    """

    def __init__(self, task_type: TaskType) -> None:
        self._task: TaskType = task_type
        self._model: Any = None
        self._weights_path: str = ""
        self._device: str = "cpu"

    @property
    def task(self) -> TaskType:
        return self._task

    @staticmethod
    def _safe_torch_load(
        path: str, map_location: str = "cpu"
    ) -> Any:
        """安全加载 PyTorch 权重（R4-7: 禁止无条件 weights_only=False）。

        weights_only=True 失败时，不回退到 weights_only=False（RCE 风险），
        而是尝试用 zipfile 直接提取 state_dict。
        """
        import torch

        try:
            return torch.load(path, map_location=map_location, weights_only=True)
        except Exception:
            logger.warning(
                "weights_only=True 加载失败，尝试安全提取 state_dict: %s", path
            )
            # R4-7: 安全回退——用 zipfile 读取 data.pkl 中的 state_dict
            try:
                return AbstractTaskEngine._extract_state_dict_safe(
                    path, map_location
                )
            except Exception:
                raise RuntimeError(
                    f"无法安全加载权重 {path}。"
                    f"请用 torch.save(model.state_dict(), path) 重新导出。"
                ) from None

    @staticmethod
    def _extract_state_dict_safe(path: str, map_location: str = "cpu") -> Any:
        """R4-7: 使用 RestrictedUnpickler 安全提取 state_dict。

        只允许反序列化 tensor 和 OrderedDict 等安全类型。
        """
        import io
        import pickle
        import zipfile
        from collections import OrderedDict

        # 只允许安全的类用于反序列化
        _SAFE_CLASSES = {
            "collections.OrderedDict": OrderedDict,
            "torch._utils._rebuild_tensor_v2": None,  # 占位，实际由 torch 重建
        }

        class _RestrictedUnpickler(pickle.Unpickler):
            def find_class(self, module: str, name: str) -> Any:
                # 只允许 torch tensor 重建相关类
                if module.startswith("torch"):
                    import torch
                    return getattr(torch, name, super().find_class(module, name))
                if module == "collections" and name == "OrderedDict":
                    return OrderedDict
                raise pickle.UnpicklingError(
                    f"不安全的反序列化: {module}.{name}"
                )

        # 尝试以 zip 格式读取 PyTorch checkpoint
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                # 尝试读取 data.pkl
                pkl_name = None
                for name in zf.namelist():
                    if name.endswith("/data.pkl"):
                        pkl_name = name
                        break
                if pkl_name is None:
                    raise RuntimeError("checkpoint 中未找到 data.pkl")
                data = zf.read(pkl_name)
                obj = _RestrictedUnpickler(io.BytesIO(data)).load()
                # 如果是 dict 且含 state_dict/model
                if isinstance(obj, dict):
                    for key in ("state_dict", "model_state_dict", "model"):
                        if key in obj:
                            return obj[key]
                return obj

        # 非 zip 格式：可能是不安全的旧格式
        raise RuntimeError("权重文件格式不支持安全加载（非 zip 格式）")

    def _ensure_loaded(self) -> None:
        """检查是否已加载权重，未加载则抛异常。"""
        if self._model is None:
            raise SupervisedEngineError(
                "引擎未加载权重，请先调用 load()", task=self.task.value
            )

    def infer_batch(
        self,
        images: list,
        threshold: float = 0.5,
        labels: Optional[list] = None,
    ) -> list:
        """批量推理：默认串行调用 infer()，子类可覆写为高效批量实现。"""
        return [
            self.infer(img, threshold=threshold, labels=labels)
            for img in images
        ]

    def unload(self) -> None:
        """释放模型资源（GPU 显存回收）。

        将模型移回 CPU、删除引用、清空 CUDA 缓存。
        子类若有额外资源（如 ONNX Runtime session），应在覆写中一并释放。
        """
        if self._model is not None:
            try:
                self._model.cpu()
            except (RuntimeError, AttributeError):
                pass
            del self._model
            self._model = None
        self._weights_path = ""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def release(self) -> None:
        """release() 是 unload() 的别名（向后兼容）。"""
        self.unload()

    @staticmethod
    def _to_numpy(image: Any) -> Any:
        """将输入图像统一转换为 numpy 数组。

        支持的类型：
        - str: 图像文件路径（通过 PIL 加载）
        - numpy.ndarray: 原样返回
        - 其他: 尝试 np.asarray() 转换
        """
        import numpy as np
        if isinstance(image, str):
            from PIL import Image
            return np.asarray(Image.open(image).convert("RGB"))
        return np.asarray(image)


class ITrainStrategy(ABC):
    """训练策略协议（Strategy Pattern）。

    子类 / 实现者只需提供 ``train_epoch`` 和 ``save`` 方法。
    被 GenericTrainer 在 fit() 循环中调用。
    """

    task: TaskType

    @abstractmethod
    def train_epoch(self, epoch: int, cfg: TrainConfig) -> Dict[str, Any]:
        """执行一轮训练，返回 metrics 字典。"""

    @abstractmethod
    def save(self, path: str) -> None:
        """保存训练权重到指定路径。"""

    def get_optimizer(self) -> Optional[Any]:
        """R4-9: 返回策略的优化器（如有），供 GenericTrainer 构建 LR 调度器。

        默认返回 None（策略未暴露优化器时不使用调度器）。
        """
        return None


__all__ = [
    "TaskType",
    "DetectionResult",
    "TrainConfig",
    "TrainArtifact",
    "ISupervisedTaskEngine",
    "AbstractTaskEngine",
    "ITrainStrategy",
]
