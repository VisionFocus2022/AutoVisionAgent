"""bool 掩码 RLE 编解码（W6-T2，对标 supervision CompactMask 的游程思路）。

线格式 ``bool_rle``（自控、文档化，跨语言可直接实现）：
- 将 (…, H, W) bool 掩码按 C 序展平为 0/1 序列；
- 编码为 int32 小端**交替游程**，从 False 游程开始：
  ``[n_false, n_true, n_false, …]``，各游程之和 == 元素总数；
- 形状不进载荷，由句柄 shape 字段携带。

对比 sv CompactMask：其内部 rles/crop_shapes 为私有字段，不宜作跨语言线
格式；本编码与 COCO/CompactMask 同为游程思想，稀疏工业掩码压缩比同量级
（见 test_compression_ratio_sparse_industrial）。
"""
from __future__ import annotations

import numpy as np

_INT32 = np.dtype("<i4")


def encode_mask_rle(mask: np.ndarray) -> bytes:
    """bool 掩码 → RLE 字节（int32 小端交替游程，False 起始）。"""
    flat = np.asarray(mask).astype(np.bool_).reshape(-1)
    n = flat.size
    if n == 0:
        return b""

    # 变更点切分游程：idx = 每段起点；首段起点 0，值 False（首像素若为 True，
    # 则首段 False 游程长度为 0）
    change = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    starts = np.concatenate(([0], change, [n]))
    lengths = np.diff(starts).astype(_INT32)

    # flat[0] 为 True 时补 0 长度首段（保持"False 起始"契约）
    if flat[0]:
        lengths = np.concatenate(([np.int32(0)], lengths))
    return lengths.tobytes()


def decode_mask_rle(data: bytes, shape) -> np.ndarray:
    """RLE 字节 → bool 掩码（按 shape 还原）。"""
    shape = tuple(int(s) for s in shape)
    total = int(np.prod(shape, dtype=np.int64)) if shape else len(data) * 8

    if len(data) == 0:
        if total == 0:
            return np.zeros(shape, dtype=np.bool_)
        raise ValueError("空 RLE 载荷无法还原非空掩码")

    runs = np.frombuffer(data, dtype=_INT32)
    if runs.sum() != total:
        raise ValueError(
            f"RLE 游程之和 {int(runs.sum())} != 形状元素数 {total}"
        )

    values = np.zeros((runs.size, 1), dtype=np.bool_)
    values[1::2] = True  # 奇数位游程为 True
    flat = np.repeat(values.reshape(-1), runs)
    return flat.reshape(shape)


__all__ = ["decode_mask_rle", "encode_mask_rle"]
