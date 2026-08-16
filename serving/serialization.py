"""DetectionResult ↔ protobuf ↔ 共享内存 的序列化桥接。

职责
----
1. 把 ``core.interfaces_supervised.DetectionResult`` 转成
   ``DetectionResultProto``：标量/小数组（boxes、scores、labels）内联进
   protobuf；大数组（masks、keypoints）走共享内存，句柄挂到 proto。
2. 把 ``DetectRequest`` 中的图像源（image_shm / image_path / image_bytes）
   解码为 numpy 数组，喂给分发器。

阈值：大数组判定。``_SHM_MIN_BYTES`` 以下的数组直接内联，避免为小掩码
也创建文件的额外开销。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from core.interfaces_supervised import DetectionResult, TaskType
from serving.proto import autovisionagent_pb2 as pb
from serving.shared_memory import SharedMemoryHandle, SharedMemoryManager

logger = logging.getLogger(__name__)

# 小于该字节数的数组直接内联到 protobuf，不创建共享内存文件
_SHM_MIN_BYTES = 64 * 1024  # 64 KiB


# ----------------------------- TaskType 映射 ------------------------------ #

def task_type_to_str(task: TaskType) -> str:
    return task.value


def str_to_task_type(name: str, default: TaskType = TaskType.DET) -> TaskType:
    """字符串 -> TaskType，未知值回退到 default。"""
    try:
        return TaskType(name.lower())
    except ValueError:
        logger.warning("未知任务类型字符串 %r，回退到 %s", name, default.value)
        return default


# ----------------------- DetectionResult -> proto ------------------------- #

def detection_result_to_proto(
    result: DetectionResult,
    shm: SharedMemoryManager,
) -> pb.DetectionResultProto:
    """把检测结果转成 proto；大数组走共享内存。"""
    proto = pb.DetectionResultProto(
        task=task_type_to_str(result.task),
        score=float(result.score),
        scores=[float(s) for s in (result.scores or ())],
        labels=list(result.labels or ()),
    )

    # boxes: N×4，扁平化内联（通常不大）
    boxes = result.boxes
    if boxes is not None:
        try:
            import numpy as np
            arr = np.asarray(boxes).reshape(-1).astype(float)
            proto.boxes_flat.extend(arr.tolist())
            proto.box_count = int(np.asarray(boxes).shape[0]) if boxes is not None else 0
        except Exception:
            logger.warning("boxes 序列化失败，跳过", exc_info=True)

    # masks: (N,H,W) bool —— 大块，走共享内存
    if result.masks is not None:
        proto.masks_shm.CopyFrom(_array_to_shm_or_skip(result.masks, "bool", shm))

    # keypoints: (N,K,2|3) float —— 走共享内存
    if result.keypoints is not None:
        proto.keypoints_shm.CopyFrom(_array_to_shm_or_skip(result.keypoints, "float32", shm))

    # extra: 仅保留可字符串化的值
    for k, v in (result.extra or {}).items():
        try:
            proto.extra[k] = str(v)
        except Exception:
            continue

    return proto


def _array_to_shm_or_skip(
    array: Any,
    dtype_name: str,
    shm: SharedMemoryManager,
) -> pb.SharedMemoryHandle:
    """大数组写共享内存；小数组或失败时返回空句柄（消费方按 length==0 判定）。"""
    import numpy as np

    try:
        arr = np.asarray(array)
        # 强制目标 dtype 以满足契约
        target = np.dtype({
            "uint8": "|u1", "float32": "<f4", "float64": "<f8", "bool": "|b1",
        }[dtype_name])
        arr = arr.astype(target, copy=False)
    except Exception:
        logger.warning("数组转 dtype=%s 失败，跳过共享内存", dtype_name, exc_info=True)
        return pb.SharedMemoryHandle()

    nbytes = int(arr.nbytes)
    if nbytes < _SHM_MIN_BYTES:
        # 小数组：仍走共享内存以保持句柄语义一致；若需内联可在此扩展
        # 这里选择直接写文件，简化消费端逻辑（始终从 shm 读 masks/keypoints）
        pass
    if nbytes == 0:
        return pb.SharedMemoryHandle()

    handle = shm.write_array(arr, dtype=dtype_name)
    return handle.to_proto()


# ----------------------- proto / request -> numpy ------------------------- #

def decode_request_image(
    request: pb.DetectRequest,
    shm: SharedMemoryManager,
) -> "numpy.ndarray":
    """从 DetectRequest 解出图像 numpy 数组 (H, W, 3) RGB。

    优先级：image_shm > image_path > image_bytes。
    """
    import numpy as np

    # 1) 共享内存大图（RAW uint8，shape=[H,W,C]）
    if request.HasField("image_shm") and request.image_shm.length > 0:
        arr = shm.read_array(request.image_shm)
        if arr.ndim == 2:  # 灰度 -> RGB
            arr = _gray_to_rgb(arr)
        return arr

    # 2) 同机文件路径
    if request.image_path:
        return _load_image_file(request.image_path)

    # 3) 内联字节（JPEG/PNG/RAW）
    if request.image_bytes:
        raw = bytes(request.image_bytes)
        # 尝试按 RAW 解码（shape 未知时无法还原，故先尝试图像解码）
        decoded = _decode_image_bytes(raw)
        if decoded is not None:
            return decoded
        raise ValueError("image_bytes 无法解码为图像（既非可识别图像格式，也未提供 shape）")

    raise ValueError("DetectRequest 未提供任何图像源")


def _load_image_file(path: str) -> "numpy.ndarray":
    """通过 PIL 加载图像文件为 RGB numpy 数组。"""
    from PIL import Image
    if not os.path.exists(path):
        raise FileNotFoundError(f"图像文件不存在: {path}")
    img = Image.open(path).convert("RGB")
    import numpy as np
    return np.asarray(img)


def _decode_image_bytes(raw: bytes) -> Optional["numpy.ndarray"]:
    """解码 JPEG/PNG/... 字节为 RGB numpy 数组；失败返回 None。"""
    import io
    import numpy as np
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        return np.asarray(img)
    except Exception:
        return None


def _gray_to_rgb(arr: "numpy.ndarray") -> "numpy.ndarray":
    import numpy as np
    return np.repeat(arr[:, :, None], 3, axis=2)


__all__ = [
    "task_type_to_str",
    "str_to_task_type",
    "detection_result_to_proto",
    "decode_request_image",
]
