"""VisionModelSystem 双范式分发（FR-F）— T-AVA-14

统一调度接口：
- 零样本范式：可注入的零样本检测器（仅预留注入点 load_zero_shot，
  当前无内置实现——DINOv3/CLIP 方案已随 W13 config 收敛移除——
  亦无生产调用方，故 list_all_tasks 不再对外广告该能力，P2-8 诚实化）
- 有监督范式：9 种任务引擎（cls/det/seg/pseg/pose/sseg/abdet/sgan/super）

根据 task_type 自动选择范式并路由到正确的引擎实例。
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from core.interfaces_supervised import (
    DetectionResult,
    ISupervisedTaskEngine,
    TaskType,
)
from models.supervised.registry import get_engine

logger = logging.getLogger(__name__)

# 零样本任务（无需训练，直接推理）
_ZERO_SHOT_TASKS = {TaskType.ABDET}

# 有监督任务（需要训练后推理）
_SUPERVISED_TASKS = {
    TaskType.CLS, TaskType.DET, TaskType.SEG,
    TaskType.PSEG, TaskType.POSE, TaskType.SSEG,
    TaskType.SGAN, TaskType.SUPER,
}


class VisionModelDispatcher:
    """双范式统一分发器。

    使用方式：
    1. 零样本：dispatcher.infer_zero_shot(image, prompts) → DetectionResult
    2. 有监督：dispatcher.infer_supervised(task, weights, image) → DetectionResult
    3. 统一：dispatcher.infer(task, image, **kwargs) → 自动路由
    """

    def __init__(self, max_loaded: int = 2) -> None:
        self._zero_shot_detector: Any = None
        # R5-10: LRU 显存管理 — 超过 max_loaded 时驱逐最久未用的引擎
        self._engines: "OrderedDict[TaskType, ISupervisedTaskEngine]" = OrderedDict()
        self._max_loaded = max_loaded
        self._engine_registry_ready = False
        # W1: gRPC ThreadPool 多工作线程并发调用，_engines 复合操作需互斥
        self._lock = threading.RLock()

    def _ensure_registry(self) -> None:
        """惰性触发引擎注册。"""
        if not self._engine_registry_ready:
            from models.supervised.engines import register_all_engines
            register_all_engines()
            self._engine_registry_ready = True

    # ---- 零样本范式 ----

    def load_zero_shot(self, detector: Any) -> None:
        """注入零样本检测器实例。"""
        self._zero_shot_detector = detector
        logger.info("零样本检测器已加载")

    def infer_zero_shot(
        self,
        image: Any,
        prompts: Optional[List[str]] = None,
        threshold: float = 0.3,
    ) -> DetectionResult:
        """零样本推理。"""
        if self._zero_shot_detector is None:
            raise RuntimeError("零样本检测器未加载")
        result = self._zero_shot_detector.detect(image, prompts, threshold)
        # 转为零样本 DetectionResult（task=ABDET 兼容）
        if isinstance(result, DetectionResult):
            return result
        return DetectionResult(
            task=TaskType.ABDET,
            score=float(getattr(result, "score", 0.5)),
            labels=tuple(prompts or []),
        )

    # ---- 有监督范式 ----

    def load_supervised(
        self,
        task: TaskType,
        weights_path: str,
        device: str = "cuda",
    ) -> None:
        """加载指定任务的有监督引擎。"""
        self._ensure_registry()
        if task not in _SUPERVISED_TASKS and task != TaskType.ABDET:
            raise ValueError(f"不支持的监督任务: {task}")

        engine = get_engine(task)
        engine.load(weights_path, device=device)
        # W1: 驱逐+插入为复合临界区（持锁）；释放显存可能含 GPU 同步，移到锁外
        evicted: list = []
        with self._lock:
            if task in self._engines:
                del self._engines[task]
            while len(self._engines) >= self._max_loaded:
                evicted.append(self._engines.popitem(last=False))
            self._engines[task] = engine
        for _evicted_task, _evicted_engine in evicted:
            _release = getattr(_evicted_engine, "release", None) or getattr(_evicted_engine, "unload", None)
            if callable(_release):
                try:
                    _release()
                except (RuntimeError, OSError):
                    logger.warning("驱逐引擎 %s 时释放显存失败", _evicted_task.value, exc_info=True)
            logger.info("LRU 驱逐引擎: %s", _evicted_task.value)
        logger.info("有监督引擎已加载: %s → %s", task.value, weights_path)

    def infer_supervised(
        self,
        task: TaskType,
        image: Any,
        threshold: float = 0.5,
        labels: Optional[List[str]] = None,
    ) -> DetectionResult:
        """有监督推理。"""
        # W1: check+touch+get 为复合临界区（防止并发驱逐穿插导致 KeyError）；
        # engine.infer 长耗时，保持在锁外
        with self._lock:
            if task not in self._engines:
                raise RuntimeError(f"任务 {task.value} 引擎未加载")
            # R5-10: LRU touch — 标记为最近使用
            self._engines.move_to_end(task)
            engine = self._engines[task]
        return engine.infer(image, threshold=threshold, labels=labels)

    # ---- 统一分发 ----

    def infer(
        self,
        task: str,
        image: Any,
        mode: str = "auto",
        **kwargs: Any,
    ) -> DetectionResult:
        """
        统一推理入口。

        Args:
            task: 任务类型字符串（cls/det/seg/pseg/pose/sseg/abdet/sgan/super/zero_shot）。
            image: 输入图像。
            mode: "auto" / "zero_shot" / "supervised"。
                - auto: task=zero_shot 或 abdet 且无引擎 → 零样本；
                        否则有监督。
            **kwargs: 各范式参数。

        Returns:
            DetectionResult。
        """
        # 特殊：zero_shot
        if task == "zero_shot":
            return self.infer_zero_shot(image, **kwargs)

        task_type = TaskType(task.lower()) if task.lower() in [
            t.value for t in TaskType
        ] else TaskType.DET

        # 模式决策
        use_supervised = mode == "supervised" or (
            mode == "auto" and task_type in self._engines
        )

        if use_supervised and task_type in self._engines:
            return self.infer_supervised(task_type, image, **kwargs)
        elif task_type == TaskType.ABDET and self._zero_shot_detector is not None:
            return self.infer_zero_shot(image, **kwargs)
        elif use_supervised:
            raise RuntimeError(
                f"任务 {task_type.value} 需先调用 load_supervised()"
            )
        else:
            raise RuntimeError(
                f"无可用引擎处理任务 {task_type.value}（mode={mode}）"
            )

    # ---- 状态查询 ----

    @property
    def loaded_tasks(self) -> List[str]:
        """已加载的有监督任务列表。"""
        with self._lock:
            return [t.value for t in self._engines]

    @property
    def zero_shot_ready(self) -> bool:
        """零样本检测器是否就绪。"""
        return self._zero_shot_detector is not None

    def get_task_info(self, task: str) -> Dict[str, Any]:
        """获取任务信息。"""
        if task == "zero_shot":
            return {
                "task": "zero_shot",
                "paradigm": "zero-shot",
                "loaded": self.zero_shot_ready,
                "requires_training": False,
            }
        # R5-9: 无效任务防御
        try:
            task_type = TaskType(task.lower())
        except ValueError:
            return {
                "task": task,
                "paradigm": "unknown",
                "loaded": False,
                "requires_training": False,
            }
        is_supervised = task_type in _SUPERVISED_TASKS
        return {
            "task": task_type.value,
            "paradigm": "supervised" if is_supervised else "zero-shot",
            "loaded": task_type in self._engines,
            "requires_training": is_supervised,
        }

    @staticmethod
    def list_all_tasks() -> List[Dict[str, Any]]:
        """列出**实际已注册**的有监督任务（W4-T2 诚实宣称 + W14 P2-8 零样本摘除）。

        注册表为空时先触发一次惰性注册（缺依赖的引擎记 warning 跳过），
        绝不广告未注册任务（era-4 诚实宣称原则）。零样本检测器为预留
        注入点（无内置实现、无调用方），不再对外广告，避免 ListTasks
        向 gRPC/C# 客户端宣称不可用能力（P2-8）。
        """
        tasks: List[Dict[str, Any]] = []
        try:
            from models.supervised.registry import get_default_registry
            reg = get_default_registry()
            if not reg.list():
                from models.supervised.engines import register_all_engines
                register_all_engines()
            for tt in reg.list():
                tasks.append({
                    "task": tt.value,
                    "paradigm": "supervised",
                    "requires_training": True,
                })
        except Exception:
            logger.warning("任务枚举失败，返回空任务清单", exc_info=True)
        return tasks


# 单例
_dispatcher: Optional[VisionModelDispatcher] = None


def get_dispatcher() -> VisionModelDispatcher:
    """获取全局分发器单例。"""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = VisionModelDispatcher()
    return _dispatcher


__all__ = ["VisionModelDispatcher", "get_dispatcher"]
