"""bool 掩码 RLE 编解码（W6-T2，对标 supervision CompactMask 的游程思路）。

线格式 ``bool_rle``（自控、文档化，跨语言可直接实现）：
- 将 (…, H, W) bool 掩码按 C 序展平为 0/1 序列；
- 编码为 int32 小端**交替游程**，从 False 游程开始：
  ``[n_false, n_true, n_false, …]``，各游程之和 == 元素总数；
- 形状不进载荷，由句柄 shape 字段携带。

对比 sv CompactMask：其内部 rles/crop_shapes 为私有字段，不宜作跨语言线
格式；本编码与 COCO/CompactMask 同为游程思想，稀疏工业掩码压缩比同量级
（见 test_compression_ratio_sparse_industrial）。

W45·P3-15：自 serving/mask_codec.py 下沉（纯函数零改动）——gui 不得引
serving 并列入口层；serving.mask_codec 保留 re-export shim 兼容。
"""
from __future__ import annotations

import os

import numpy as np

_INT32 = np.dtype("<i4")

# ---- S2（安全审查 2026-10-05）：解码上限防护 ----
# 恶意/损坏载荷可声明巨大形状（如 runs=[N]+shape 总积 N=数十亿）令
# np.repeat 分配 N 字节打爆服务进程；且游程按 int32 求和在 ~2^31 处回绕，
# 可构造绕过 sum==total 校验。解码前强制三道闸：
# 载荷长度对齐、元素总数上限、负游程拒绝 + int64 求和。
_MAX_DECODE_ELEMENTS_ENV = "AVA_MASK_RLE_MAX_ELEMENTS"
_DEFAULT_MAX_DECODE_ELEMENTS = 1 << 30  # 10 亿像素 ≈ 1 GiB bool，远超工业图像常规量级

# 空载荷解码为全 False 掩码的元素上限（无 shape 线格式回退路径）：空载荷
# 默认按 len(data)*8 推 total，该路径不分配大内存，无需额外闸门。
# 有 shape 路径已由 _resolve_max_decode_elements 控制。


def encode_mask_rle(mask: np.ndarray) -> bytes:
    """bool 掩码 → RLE 字节（int32 小端交替游程，False 起始）。

    S2（安全审查 2026-10-05）：掩码元素数超过 int32 游程表示范围时
    显式拒绝，防止 astype(int32) 静默回绕产生损坏载荷。
    """
    flat_view = np.asarray(mask)
    n = flat_view.size
    if n == 0:
        return b""
    if n > np.iinfo(np.int32).max:
        raise ValueError(
            f"掩码元素数 {n} 超出 int32 游程可表示上限（2^31-1），拒绝编码"
        )
    # 上限校验须在 astype 之前：astype 会按 n 分配内存，先验后转防
    # 超大输入在拒绝前就触发内存峰值
    flat = flat_view.astype(np.bool_).reshape(-1)

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
    """RLE 字节 → bool 掩码（按 shape 还原）。

    S2（安全审查 2026-10-05）：对外服务入口的恶意/损坏载荷防护——
    校验元素总数上限（防 OOM）、载荷长度 4 字节对齐、负游程拒绝、
    int64 求和（防 int32 回绕绕过总量校验）。
    """
    shape = tuple(int(s) for s in shape)
    total = int(np.prod(shape, dtype=np.int64)) if shape else len(data) * 8

    # 闸 1：元素总数上限（防恶意 shape 声明几十亿像素致 np.repeat OOM）
    max_elements = _resolve_max_decode_elements()
    if total > max_elements:
        raise ValueError(
            f"RLE 解码元素总数 {total} 超过上限 {max_elements}"
            f"（{_MAX_DECODE_ELEMENTS_ENV} 可调）"
        )
    if total < 0 or any(s < 0 for s in shape):
        raise ValueError(f"RLE 形状含负数: {shape}")

    if len(data) == 0:
        if total == 0:
            return np.zeros(shape, dtype=np.bool_)
        raise ValueError("空 RLE 载荷无法还原非空掩码")

    # 闸 2：载荷长度必须 4 字节对齐（int32 小端游程，非对齐即损坏/伪造）
    if len(data) % 4 != 0:
        raise ValueError(
            f"RLE 载荷长度 {len(data)} 不是 4 的倍数（int32 游程损坏）"
        )

    runs = np.frombuffer(data, dtype=_INT32)
    # 闸 3：负游程无意义（伪造载荷）；int64 求和防 int32 回绕绕过校验
    if runs.size and int(runs.min()) < 0:
        raise ValueError("RLE 游程含负值（载荷损坏或伪造）")
    runs_sum = int(runs.sum(dtype=np.int64)) if runs.size else 0
    if runs_sum != total:
        raise ValueError(
            f"RLE 游程之和 {runs_sum} != 形状元素数 {total}"
        )

    values = np.zeros((runs.size, 1), dtype=np.bool_)
    values[1::2] = True  # 奇数位游程为 True
    flat = np.repeat(values.reshape(-1), runs)
    return flat.reshape(shape)


__all__ = ["decode_mask_rle", "encode_mask_rle"]


def _resolve_max_decode_elements() -> int:
    """解析解码元素上限：环境变量 AVA_MASK_RLE_MAX_ELEMENTS > 默认 2^30。

    <= 0 视为配置错误，回退默认值并告警（fail-safe 而非 fail-open）。
    模块级缓存：热路径每次 decode 不重复解析 env/日志。
    """
    global _CACHED_MAX_DECODE_ELEMENTS
    cached = globals().get("_CACHED_MAX_DECODE_ELEMENTS")
    if cached is not None:
        return cached
    raw = os.environ.get(_MAX_DECODE_ELEMENTS_ENV)
    value = _DEFAULT_MAX_DECODE_ELEMENTS
    if raw:
        try:
            parsed = int(raw)
            value = parsed if parsed > 0 else _DEFAULT_MAX_DECODE_ELEMENTS
            if parsed <= 0:
                import logging

                logging.getLogger(__name__).warning(
                    "环境变量 %s=%r 非正数，回退默认值 %d",
                    _MAX_DECODE_ELEMENTS_ENV, raw, _DEFAULT_MAX_DECODE_ELEMENTS,
                )
        except ValueError:
            import logging

            logging.getLogger(__name__).warning(
                "环境变量 %s=%r 不是整数，回退默认值 %d",
                _MAX_DECODE_ELEMENTS_ENV, raw, _DEFAULT_MAX_DECODE_ELEMENTS,
            )
    _CACHED_MAX_DECODE_ELEMENTS = value
    return value
