"""
有监督任务引擎注册表

提供 @register_engine 装饰器，将各任务引擎（实现 ISupervisedTaskEngine）
按 TaskType 注册到默认注册表。

用法（M1+ 实现具体引擎时）::

    from core.interfaces_supervised import TaskType
    from models.supervised import AbstractTaskEngine, register_engine

    @register_engine(TaskType.DET)
    class DetYoloEngine(AbstractTaskEngine):
        ...

运行时分发::

    from models.supervised import get_engine
    engine = get_engine(TaskType.DET)
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional

from core.exceptions import UnsupportedTaskError
from core.interfaces_supervised import ISupervisedTaskEngine, TaskType

EngineFactory = Callable[[], ISupervisedTaskEngine]


class EngineRegistry:
    """任务引擎注册表（工厂 + 实例缓存）。"""

    def __init__(self) -> None:
        self._factories: Dict[TaskType, EngineFactory] = {}
        self._cache: Dict[TaskType, ISupervisedTaskEngine] = {}
        self._lock = threading.RLock()

    def register(self, task: TaskType, factory: EngineFactory) -> None:
        """注册任务引擎工厂。"""
        with self._lock:
            self._factories[task] = factory

    def has(self, task: TaskType) -> bool:
        with self._lock:
            return task in self._factories

    def get(self, task: TaskType) -> ISupervisedTaskEngine:
        """获取引擎实例（首次调用走工厂，之后命中缓存）。

        使用 RLock 保证多线程并发时只创建一个实例。
        """
        # 快速路径：无锁读缓存（best-effort，命中则直接返回）
        cached = self._cache.get(task)
        if cached is not None:
            return cached

        with self._lock:
            # double-check：可能在等待锁期间已被其他线程创建
            cached = self._cache.get(task)
            if cached is not None:
                return cached
            if task not in self._factories:
                raise UnsupportedTaskError(task.value)
            engine = self._factories[task]()
            self._cache[task] = engine
            return engine

    def list(self) -> List[TaskType]:
        with self._lock:
            return sorted(self._factories.keys(), key=lambda t: t.value)

    def clear_cache(self, task: Optional[TaskType] = None) -> None:
        """清除实例缓存（不注销工厂），并释放引擎占用的 GPU 显存。

        task=None 清全部；否则只清指定任务。
        """
        import logging
        _logger = logging.getLogger(__name__)
        with self._lock:
            if task is None:
                items = list(self._cache.items())
                self._cache.clear()
            else:
                engine = self._cache.pop(task, None)
                items = [(task, engine)] if engine is not None else []

        # 在锁外执行 unload（可能涉及 GPU 同步，避免长时间持锁）
        for _task, engine in items:
            try:
                engine.unload()
            except Exception:
                _logger.warning("卸载引擎 %s 时出错", _task.value, exc_info=True)


# 默认全局注册表
_default_registry = EngineRegistry()


def register_engine(
    task_type: TaskType,
    factory: Optional[EngineFactory] = None,
    registry: Optional[EngineRegistry] = None,
) -> Callable[[type], type]:
    """
    类装饰器：注册任务引擎。

    Args:
        task_type: 任务类型。
        factory: 可选工厂；默认 ``lambda: Cls()``。
        registry: 可选注册表；默认全局表。
    """

    reg = registry if registry is not None else _default_registry

    def decorator(cls: type) -> type:
        f: EngineFactory = factory if factory is not None else (lambda: cls())  # type: ignore
        reg.register(task_type, f)
        return cls

    return decorator


def get_engine(
    task_type: TaskType, registry: Optional[EngineRegistry] = None
) -> ISupervisedTaskEngine:
    """从默认（或指定）注册表获取引擎实例。"""
    reg = registry if registry is not None else _default_registry
    return reg.get(task_type)


def get_default_registry() -> EngineRegistry:
    """返回默认全局注册表。"""
    return _default_registry


__all__ = [
    "EngineRegistry",
    "EngineFactory",
    "register_engine",
    "get_engine",
    "get_default_registry",
]
