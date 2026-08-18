"""DetectionResult ↔ protobuf ↔ 共享内存 的序列化桥接。

职责
----
1. 把 ``core.interfaces_supervised.DetectionResult`` 转成
   ``DetectionResultProto``：标量/小数组（boxes、scores、labels）内联进
   protobuf；大数组（masks、keypoints）走共享内存，句柄挂到 proto。
2. 把 ``DetectRequest`` 中的图像源（image_shm / image_path / image_bytes）
   解码为 numpy 数组，喂给分发器。

阈值：大数组判定。序列化后（bool 掩码经 RLE）小于 ``_SHM_MIN_BYTES`` 的
载荷直接内联进 proto 的 masks_inline/keypoints_inline 字段（W17，v3 P1-1：
结果区域由客户端在 RPC 返回后即读，小载荷内联不再消耗 shm 区域配额——
随附 C# 客户端结构性无法回收结果区域）；大于阈值仍走共享内存文件。
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

    # P3⑤（W17 簇C）：部分失败回滚——masks/keypoints 两段载荷写入期间任一
    # 后续步骤抛异常，客户端不会收到任何句柄，此前已成功创建的 shm 区域将
    # 成为无主泄漏（登记表占位 + 磁盘文件残留）。记录已落地区域路径，
    # 异常时先逐个 release 再上抛（inline 载荷 file_path 为空，不记录）。
    created_region_paths: list[str] = []
    try:
        # masks: (N,H,W) bool —— 小掩码内联（W17），大掩码走共享内存
        if result.masks is not None:
            inline, handle = _array_payload(result.masks, "bool", shm, rle=True)
            if handle.file_path:
                created_region_paths.append(handle.file_path)
            proto.masks_shm.CopyFrom(handle)
            if inline is not None:
                proto.masks_inline = inline

        # keypoints: (N,K,2|3) float —— 同契约
        if result.keypoints is not None:
            inline, handle = _array_payload(result.keypoints, "float32", shm, rle=False)
            if handle.file_path:
                created_region_paths.append(handle.file_path)
            proto.keypoints_shm.CopyFrom(handle)
            if inline is not None:
                proto.keypoints_inline = inline
    except BaseException:
        for path in created_region_paths:
            try:
                shm.release(path)
            except Exception:
                # 回滚本身失败不得掩盖原始异常，但必须留痕（不得静默吞）
                logger.warning(
                    "部分失败回滚共享内存区域失败: %s", path, exc_info=True
                )
        raise

    # extra: 仅保留可字符串化的值
    for k, v in (result.extra or {}).items():
        try:
            proto.extra[k] = str(v)
        except Exception:
            # W14-C3（P2-13）：跳过不可字符串化键时留痕，避免静默丢字段难排查
            logger.warning("extra[%r] 字符串化失败，跳过该键", k, exc_info=True)
            continue

    return proto


def _array_payload(
    array: Any,
    dtype_name: str,
    shm: SharedMemoryManager,
    *,
    rle: bool,
):
    """序列化大数组，返回 ``(inline_bytes | None, SharedMemoryHandle)``。

    W17（v3 P1-1）小数组内联：序列化后（bool 掩码经 RLE，默认开启，
    AVA_SHM_MASK_RLE=0 退回 raw）字节少于 ``_SHM_MIN_BYTES`` 的载荷直接
    内联——返回的句柄仅作 dtype/shape 元数据载体（file_path 空、length 0），
    不创建共享内存区域、不消耗区域配额。大载荷仍走 shm 区域，inline 为 None。

    失败/空数组语义与旧 ``_array_to_shm_or_skip`` 一致：返回 (None, 空句柄)，
    消费方按 length==0 判定缺失。
    """
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
        return None, pb.SharedMemoryHandle()

    shape = tuple(int(s) for s in arr.shape)

    if rle and os.environ.get("AVA_SHM_MASK_RLE", "1") == "1":
        from serving.mask_codec import encode_mask_rle

        payload = encode_mask_rle(arr)
        wire_dtype = "bool_rle"
    else:
        payload = arr.tobytes(order="C")
        wire_dtype = dtype_name

    if len(payload) == 0:
        return None, pb.SharedMemoryHandle()

    if len(payload) < _SHM_MIN_BYTES:
        # 小数组内联：句柄只携带 dtype/shape 元数据（file_path 空、length 0）
        return payload, pb.SharedMemoryHandle(
            dtype=wire_dtype, shape=list(shape)
        )

    handle = shm.write_bytes(payload, dtype=wire_dtype, shape=shape)
    return None, handle.to_proto()


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
        # W14-C3（P2-13）：解码失败由调用方上抛 ValueError，此处先留痕
        # （字节长度/异常栈），便于区分"坏数据"与"缺 shape"
        logger.warning("image_bytes 图像解码失败（%d 字节）", len(raw), exc_info=True)
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
