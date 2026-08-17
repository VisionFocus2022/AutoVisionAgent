"""industrial_vision_platform — 工业视觉平台扩展模块。

提供视觉任务分发器 (VisionModelDispatcher)：统一推理入口 + LRU 显存管理。
"""
from __future__ import annotations

# 安全导入：子模块可能依赖不存在的第三方库
try:
    from industrial_vision_platform.vision_dispatcher import (
        VisionModelDispatcher,
        get_dispatcher,
    )
except ImportError:
    VisionModelDispatcher = None  # type: ignore
    get_dispatcher = None  # type: ignore

__all__ = [
    "VisionModelDispatcher",
    "get_dispatcher",
]
