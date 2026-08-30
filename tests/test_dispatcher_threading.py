"""VisionModelDispatcher 线程安全测试（W1-T2，P2-2）。

两层：
1. 单线程语义回归——加锁改造不得改变既有可观测行为
   （LRU 驱逐与释放、未加载 infer 报 RuntimeError、统一入口 auto 路由）。
2. 并发正确性——用 __contains__ 钩子在「成员检查通过之后、move_to_end 之前」
   植入确定性窗口，复现并发驱逐下的 KeyError（修复前必现），
   另附 8 线程混合 load/infer 压力作为护栏。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

import pytest

import industrial_vision_platform.vision_dispatcher as vp
from core.interfaces_supervised import DetectionResult, TaskType


class _FakeEngine:
    """轻量假引擎：记录 load/infer/unload 调用，无重依赖。"""

    def __init__(self, task: TaskType) -> None:
        self.task = task
        self.unload_calls = 0
        self.infer_calls = 0

    def load(self, weights_path: str, device: str = "cuda") -> None:  # noqa: ARG002
        pass

    def infer(self, image, threshold: float = 0.5, labels=None) -> DetectionResult:
        self.infer_calls += 1
        return DetectionResult(task=self.task, score=0.9)

    def unload(self) -> None:
        self.unload_calls += 1

    release = unload


@pytest.fixture
def dispatcher(monkeypatch):
    """带假引擎注册表的分发器（跳过 register_all_engines）。"""
    d = vp.VisionModelDispatcher(max_loaded=2)
    d._engine_registry_ready = True  # 跳过惰性注册（单测不依赖真实引擎模块）

    engines: dict = {}

    def fake_get_engine(task):
        return engines.setdefault(task, _FakeEngine(task))

    monkeypatch.setattr(vp, "get_engine", fake_get_engine)
    return d


# ============================ 单线程语义回归 ============================ #

@pytest.mark.unit
def test_lru_eviction_releases_oldest(dispatcher, monkeypatch):
    """max_loaded=1 场景：加载新引擎驱逐并释放最久未用引擎。"""
    dispatcher._max_loaded = 1
    engines = {}
    monkeypatch.setattr(
        vp, "get_engine",
        lambda t: engines.setdefault(t, _FakeEngine(t)),
    )
    dispatcher.load_supervised(TaskType.CLS, "w")
    dispatcher.load_supervised(TaskType.POSE, "w")
    assert engines[TaskType.CLS].unload_calls == 1  # 最旧被驱逐并释放
    assert dispatcher.loaded_tasks == [TaskType.POSE.value]


@pytest.mark.unit
def test_lru_touch_on_infer(dispatcher):
    """infer 将引擎标记为最近使用（驱逐顺序改变）。"""
    a = _FakeEngine(TaskType.CLS)
    b = _FakeEngine(TaskType.POSE)
    c = _FakeEngine(TaskType.PSEG)
    created = {TaskType.CLS: a, TaskType.POSE: b, TaskType.PSEG: c}
    import industrial_vision_platform.vision_dispatcher as mod
    orig = mod.get_engine
    mod.get_engine = lambda t: created[t]
    try:
        dispatcher._max_loaded = 2
        dispatcher.load_supervised(TaskType.CLS, "w")
        dispatcher.load_supervised(TaskType.POSE, "w")
        dispatcher.infer_supervised(TaskType.CLS, None)  # touch CLS
        dispatcher.load_supervised(TaskType.PSEG, "w")   # 应驱逐 POSE（最久未用）
        assert b.unload_calls == 1
        assert a.unload_calls == 0
        assert dispatcher.loaded_tasks == [TaskType.CLS.value, TaskType.PSEG.value]
    finally:
        mod.get_engine = orig


@pytest.mark.unit
def test_infer_without_load_raises_runtime(dispatcher):
    """未加载引擎时 infer_supervised 报 RuntimeError（而非 KeyError）。"""
    with pytest.raises(RuntimeError, match="引擎未加载"):
        dispatcher.infer_supervised(TaskType.CLS, None)


@pytest.mark.unit
def test_unified_infer_auto_routes_loaded(dispatcher):
    """统一入口 auto 模式：已加载任务走监督推理。"""
    dispatcher.load_supervised(TaskType.CLS, "w")
    result = dispatcher.infer("cls", None, mode="auto")
    assert result.task is TaskType.CLS
    assert result.score == pytest.approx(0.9)


# ============================ 并发正确性 ============================ #

@pytest.mark.unit
def test_no_keyerror_when_eviction_interleaves_check_and_move(monkeypatch):
    """确定性复现竞态窗口：检查通过后、move_to_end 前发生驱逐。

    修复前：infer_supervised 的 check→move_to_end 无锁，另一线程的
    LRU 驱逐会移除该任务 → move_to_end 抛 KeyError（fail-request 级缺陷）。
    修复后：check+move+get 由锁保护，驱逐方阻塞至本侧完成。
    """
    d = vp.VisionModelDispatcher(max_loaded=1)
    d._engine_registry_ready = True
    engines = {}
    monkeypatch.setattr(vp, "get_engine",
                        lambda t: engines.setdefault(t, _FakeEngine(t)))
    d.load_supervised(TaskType.CLS, "w")

    entered_window = threading.Event()

    class _SlowContainsOrderedDict(OrderedDict):
        """在「命中成员检查之后」放慢一次，撑开竞态窗口。"""

        def __contains__(self, key):
            hit = super().__contains__(key)
            if hit and not entered_window.is_set():
                entered_window.set()
                time.sleep(0.15)  # 窗口：返回 True 与 move_to_end 之间
            return hit

    d._engines = _SlowContainsOrderedDict(d._engines)

    unexpected: list[BaseException] = []

    def infer_thread():
        for _ in range(2):
            try:
                d.infer_supervised(TaskType.CLS, None)
            except RuntimeError:
                pass  # 「引擎未加载」是并发驱逐下的合法可见状态
            except BaseException as exc:  # noqa: BLE001
                unexpected.append(exc)

    t = threading.Thread(target=infer_thread)
    t.start()
    assert entered_window.wait(timeout=2.0), "未能进入竞态窗口（时序异常）"
    # 窗口内驱逐 CLS（max_loaded=1 → 加载 POSE 必驱逐）
    d.load_supervised(TaskType.POSE, "w")
    t.join(timeout=5.0)

    assert not unexpected, f"并发窗口内出现未预期异常: {unexpected!r}"


@pytest.mark.unit
def test_concurrent_load_infer_stress(dispatcher):
    """8 线程混合 load/infer 压力护栏：只允许「引擎未加载」RuntimeError。"""
    tasks = [TaskType.CLS, TaskType.POSE, TaskType.PSEG, TaskType.SSEG,
             TaskType.SGAN, TaskType.SUPER]
    unexpected: list[BaseException] = []
    lock = threading.Lock()

    def worker(seed: int):
        for i in range(40):
            task = tasks[(seed + i) % len(tasks)]
            try:
                if i % 3 == 0:
                    dispatcher.load_supervised(task, "w")
                else:
                    dispatcher.infer_supervised(task, None)
            except RuntimeError as exc:
                if "引擎未加载" not in str(exc):
                    with lock:
                        unexpected.append(exc)
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    unexpected.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30.0)

    assert not unexpected, f"压力测试出现未预期异常: {unexpected!r}"
    # 终态一致性：驻留引擎数不超过上限
    assert len(dispatcher.loaded_tasks) <= dispatcher._max_loaded
