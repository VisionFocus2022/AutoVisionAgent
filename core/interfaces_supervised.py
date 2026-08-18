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

# W12 安全加固：data.pkl 单条目解压后字节上限（256 MiB），
# 防 pickle 流经高压缩比 zip 条目炸弹式膨胀。
_MAX_DATA_PKL_BYTES = 256 * 1024 ** 2


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
        W12-F4: 覆写 persistent_load，从同一 zip 容器的 data/<key>
        条目按白名单 storage 类型回填 tensor 存储（绝不执行任意代码）。

        形态豁免声明（v3 P2-10）：本函数约 195 行，为函数+嵌套
        RestrictedUnpickler 安全类的内聚安全单元，有专项测试覆盖
        （tests/test_interfaces_safe_extract.py）；机械拆分会损害
        安全审计可读性，经架构审查 v3 对抗复核裁定保持整块
        （阈值超 100 行的有意豁免）。
        """
        import io
        import pickle
        import warnings
        import zipfile
        from collections import OrderedDict

        import torch

        # zip 炸弹防护：单次提取的存储总解压字节上限（2 GiB）
        _MAX_STORAGE_TOTAL_BYTES = 2 * 1024 ** 3

        # 名级精确白名单（W12 安全修复）：真实 torch.save 产 data.pkl 经
        # pickletools.dis 实测枚举出的 GLOBAL/STACK_GLOBAL 对（torch 2.5.1）：
        # ('collections','OrderedDict')、('torch._utils','_rebuild_tensor_v2')、
        # （保存 Parameter 时）('torch._utils','_rebuild_parameter')，以及
        # ('torch','<X>Storage') 各存储类名（含旧版 _rebuild_tensor 重建器）。
        # 白名单外的任何 (module, name) 一律 UnpicklingError——严禁
        # startswith('torch')+getattr 通配（GLOBAL 'torch' 'save' 经 REDUCE
        # 即任意落盘）与 super().find_class 无限制导入兜底。
        _safe_globals: Dict[Tuple[str, str], Any] = {
            ("collections", "OrderedDict"): OrderedDict,
            ("torch._utils", "_rebuild_tensor_v2"): (
                torch._utils._rebuild_tensor_v2
            ),
        }
        for _rname in ("_rebuild_parameter", "_rebuild_tensor"):
            _rfn = getattr(torch._utils, _rname, None)
            if _rfn is not None:
                _safe_globals[("torch._utils", _rname)] = _rfn
        # 个别旧版 torch 把重建器挂在顶层命名空间的写法（存在才生效）
        for _rname in ("_rebuild_tensor_v2", "_rebuild_parameter", "_rebuild_tensor"):
            _rfn = getattr(torch, _rname, None)
            if _rfn is not None:
                _safe_globals[("torch", _rname)] = _rfn

        # 存储类型白名单：torch 以 GLOBAL 'torch <X>Storage' 持久化
        # （如 'torch FloatStorage'），按类对象身份命中；本版 torch
        # 不存在的类型自动跳过。UntypedStorage 按 torch 语义视作 uint8
        # （参考 torch/serialization.py 加载侧 persistent_load）。
        _storage_dtypes: Dict[type, Any] = {}
        # 访问 torch 浮点存储类型会触发 TypedStorage 弃用 UserWarning，
        # 属预期形态探测，静默之。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for _name in (
                "FloatStorage", "DoubleStorage", "HalfStorage", "LongStorage",
                "IntStorage", "ShortStorage", "ByteStorage", "BoolStorage",
                "BFloat16Storage", "ComplexFloatStorage", "ComplexDoubleStorage",
            ):
                _stype = getattr(torch, _name, None)
                _dtype = getattr(_stype, "dtype", None)
                if isinstance(_stype, type) and _dtype is not None:
                    _storage_dtypes[_stype] = _dtype
                    _safe_globals[("torch", _name)] = _stype
            _untyped_type = getattr(torch, "UntypedStorage", None)
            if isinstance(_untyped_type, type):
                _storage_dtypes[_untyped_type] = torch.uint8
                _safe_globals[("torch", "UntypedStorage")] = _untyped_type

        class _RestrictedUnpickler(pickle.Unpickler):
            def __init__(self, file: Any, zf: Any, data_prefix: str) -> None:
                super().__init__(file)
                self._zf = zf
                self._data_prefix = data_prefix
                self._storage_bytes_read = 0

            def find_class(self, module: str, name: str) -> Any:
                # 名级精确白名单直查：未命中即拒绝（含 'torch' 'save' 等
                # 任意 torch 顶层属性；杜绝 getattr 通配与 super().find_class
                # 无限制导入兜底——后者曾作为第三参默认值被急切求值）。
                obj = _safe_globals.get((module, name))
                if obj is None:
                    raise pickle.UnpicklingError(
                        f"不安全的反序列化: {module}.{name}"
                    )
                return obj

            def persistent_load(self, pid: Any) -> Any:
                """torch zip 格式持久 ID: ('storage', storage_type, key,
                location, numel)（torch/serialization.py:1080 保存侧）。

                仅从同一 zip 的 data/<key> 条目读原始字节回填 storage；
                location 只做白名单校验（cpu/'')，绝不 eval/动态调用。
                """
                if not (isinstance(pid, tuple) and len(pid) == 5):
                    raise pickle.UnpicklingError("不安全的持久 ID 形态（非五元组）")
                typename = pid[0]
                if isinstance(typename, bytes):
                    typename = typename.decode("ascii", errors="replace")
                if typename != "storage":
                    raise pickle.UnpicklingError(
                        f"不安全的持久 ID 类型: {typename!r}"
                    )
                storage_type, key, location, numel = pid[1:]
                try:
                    dtype = _storage_dtypes.get(storage_type)
                except TypeError:
                    # 不可哈希 storage_type（如 list 字面量）归一为拒绝，
                    # 不外泄 TypeError
                    raise pickle.UnpicklingError(
                        f"不安全的存储类型（不可哈希）: {storage_type!r}"
                    ) from None
                if dtype is None:
                    raise pickle.UnpicklingError(
                        f"不安全的存储类型（非白名单）: {storage_type!r}"
                    )
                if not isinstance(key, str):
                    raise pickle.UnpicklingError("不安全的存储键（非字符串）")
                if isinstance(location, bytes):
                    location = location.decode("ascii", errors="replace")
                if location not in ("", "cpu"):
                    raise pickle.UnpicklingError(
                        f"不安全的存储位置: {location!r}"
                    )
                if type(numel) is not int or numel < 0:
                    raise pickle.UnpicklingError("不安全的存储元素数（numel）")

                nbytes = numel * torch._utils._element_size(dtype)
                if self._storage_bytes_read + nbytes > _MAX_STORAGE_TOTAL_BYTES:
                    raise pickle.UnpicklingError(
                        "超出安全加载的存储总字节上限"
                        f"（{_MAX_STORAGE_TOTAL_BYTES} 字节）"
                    )
                entry = f"{self._data_prefix}data/{key}"
                try:
                    raw = self._zf.read(entry)
                except KeyError:
                    if numel == 0:
                        raw = b""
                    else:
                        raise pickle.UnpicklingError(
                            f"存储数据条目缺失: {entry}"
                        ) from None
                if len(raw) != nbytes:
                    raise pickle.UnpicklingError(
                        f"存储数据长度与声明不符: {entry} "
                        f"期望 {nbytes} 字节，实际 {len(raw)} 字节"
                    )
                self._storage_bytes_read += nbytes

                if nbytes:
                    # clone() 确保 storage 拥有 torch 自管的内存
                    # （frombuffer 视图随临时缓冲一同销毁）
                    untyped_storage = (
                        torch.frombuffer(bytearray(raw), dtype=torch.uint8)
                        .clone()
                        .untyped_storage()
                    )
                else:
                    untyped_storage = torch.UntypedStorage(0)
                return torch.storage.TypedStorage(
                    wrap_storage=untyped_storage, dtype=dtype, _internal=True
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
                # W12 加固：单条目解压字节上限（pickle 流炸弹面）——
                # 只读 limit+1 字节探测超限，绝不整体解压超大条目。
                with zf.open(pkl_name) as pkl_fh:
                    data = pkl_fh.read(_MAX_DATA_PKL_BYTES + 1)
                if len(data) > _MAX_DATA_PKL_BYTES:
                    raise pickle.UnpicklingError(
                        "data.pkl 超出单文件字节上限"
                        f"（{_MAX_DATA_PKL_BYTES} 字节）"
                    )
                # 存储数据条目与 data.pkl 同前缀：<archive>/data/<key>
                data_prefix = pkl_name[: -len("data.pkl")]
                obj = _RestrictedUnpickler(
                    io.BytesIO(data), zf, data_prefix
                ).load()
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
