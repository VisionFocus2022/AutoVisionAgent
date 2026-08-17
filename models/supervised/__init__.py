"""有监督模型引擎包。

导出引擎基类、注册装饰器和工厂函数。
"""
from __future__ import annotations

from core.interfaces_supervised import (
    AbstractTaskEngine,
    ISupervisedTaskEngine,
    TaskType,
)
from models.supervised.registry import (
    EngineRegistry,
    get_default_registry,
    get_engine,
    register_engine,
)

__all__ = [
    "AbstractTaskEngine",
    "ISupervisedTaskEngine",
    "TaskType",
    "EngineRegistry",
    "register_engine",
    "get_engine",
    "get_default_registry",
]
