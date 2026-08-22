"""AMP 可用性预检（W31 · 对标 SKolpha checkamp 的 2 行等价替代）。

训练开始前 cuda 侧 fp16 matmul 前向+反向有限性探针；失败=训练页
警告并回退 FP32；cpu / lite（CPU torch）静默跳过——不随包 checkamp.pt
资产（随包资产 +2MB 且黑盒；本探针诚实、可读、零资产）。
"""
from __future__ import annotations

import logging
from typing import Tuple

from models.supervised.device import resolve_device

logger = logging.getLogger(__name__)


def amp_preflight(device: str) -> Tuple[bool, str]:
    """AMP 可用性探针。

    Returns:
        (ok, reason)：
        - cpu / 非 cuda → (True, "skip")——cpu 训练无 AMP 意义，静默跳过；
        - cuda 侧 fp16 前向+反向全部有限 → (True, "ok")；
        - 探针异常 / 梯度非有限 → (False, 原因)——调用方警告并回退 FP32。
    """
    resolved = str(resolve_device(device))
    if not resolved.startswith("cuda"):
        return True, "skip"
    import torch

    try:
        with torch.autocast("cuda", dtype=torch.float16):
            a = torch.randn(
                64, 64, device=resolved, dtype=torch.float16, requires_grad=True
            )
            b = a @ a
        b.sum().backward()
        if not bool(torch.isfinite(a.grad).all().item()):
            return False, "fp16 反向梯度出现非有限值"
        return True, "ok"
    except Exception as exc:  # noqa: BLE001——探针任何异常都回退 FP32
        logger.warning("AMP 预检探针失败: %s", exc)
        return False, f"fp16 autocast 探针失败: {exc}"


__all__ = ["amp_preflight"]
