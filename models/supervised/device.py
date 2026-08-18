"""引擎 device 护栏（W19 v3 第三波 FR-3.1）。

dist-lite 派生（FR-3.2/3.3 裁掉 ``_internal/torch/lib`` 内 ~3.24G CUDA 栈）后，
若调用方仍按各引擎默认 ``device="cuda"`` 加载，torch 会在无 CUDA 栈的环境里
崩溃。本模块提供 ``resolve_device``：cuda 请求但本机不可用时诚实回退 cpu 并
告警留痕；其余值（cpu/None/其他 torch device 字符串）一律原样透传，不做二次
猜测——非精确 "cuda" 的串（如 "cuda:0"）属调用方显式指定，由调用方自担。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["resolve_device"]


def resolve_device(device: Any) -> Any:
    """归一化引擎 device 参数（W19 v3 第三波 FR-3.1）。

    规则：
    - ``device`` 为字符串且 ``lower() == "cuda"``，而 ``torch.cuda.is_available()``
      为 False → 返回 ``"cpu"`` 并 ``logging.warning`` 留痕（不静默换设备）；
    - 其余一律原样返回（``"cpu"`` / None / ``"cuda:0"`` / 其他合法串）。

    torch 本身不可导入时按 "cuda 不可用" 处理（lite 产物无 CUDA 栈亦能起引擎）。

    Args:
        device: 引擎 ``load(device=...)`` 形参原值，可为 None/任意串。

    Returns:
        归一后的 device；仅精确 cuda 请求且不可用时被替换为 ``"cpu"``。
    """
    if not isinstance(device, str) or device.lower() != "cuda":
        return device
    try:
        import torch

        available = bool(torch.cuda.is_available())
    except Exception:  # torch 不可导入（lite/裁剪环境兜底）
        available = False
    if not available:
        logger.warning(
            "请求 device=cuda 但本机 CUDA 不可用，引擎回退 CPU 推理"
            "（W19 FR-3.1 device 护栏；lite 发行版为预期场景）"
        )
        return "cpu"
    return device
