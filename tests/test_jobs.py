"""gui/core/jobs.py 统一后台任务调度单测（W15-J1；架构审查 P2-1）。

纯 threading + logging，无 Qt 依赖——本文件不设 QT_QPA_PLATFORM、
不 importorskip PySide6，任何层可在无 GUI 环境消费该模块。

对照生产参考形态（只读，勿改）：gui/pages/data_manage/page.py:347-379
页内私造 _run_worker——裸 daemon Thread、无注册表（退出守卫不可见）、
无取消通道、异常路径固定 invoke_main。
"""
from __future__ import annotations

import inspect
import logging
import threading
import time

import pytest

from gui.core.jobs import JobHandle, active_jobs, request_stop_all, run_job


def _join(handle: JobHandle, timeout_s: float = 3.0) -> None:
    """有界 join 并断言线程已退出（真线程专用，FakeThread 场景勿用）。"""
    handle.thread.join(timeout_s)
    assert not handle.thread.is_alive(), f"job {handle.name!r} 线程未退出"


@pytest.fixture(autouse=True)
def _drain_registry():
    """每个用例收尾兜底：置位所有残留 cancel 并有界等待，防跨用例泄漏。"""
    yield
    request_stop_all(timeout_s=1.0)


# ============================== 注册与生命周期 ============================== #
class TestRegisterLifecycle:
    @pytest.mark.unit
    def test_registers_while_running_and_deregisters_on_completion(self):
        started = threading.Event()
        release = threading.Event()
        seen_inside: list[list[str]] = []

        def work():
            seen_inside.append(list(active_jobs()))
            started.set()
            release.wait(5)

        handle = run_job(work, name="lifecycle")
        assert isinstance(handle, JobHandle)
        assert handle.name == "lifecycle"
        assert isinstance(handle.cancel, threading.Event)
        assert started.wait(3)
        # 运行中：主线程与 worker 线程两视角均能看到注册表登记
        assert active_jobs() == ["lifecycle"]
        release.set()
        _join(handle)
        assert active_jobs() == []
        assert seen_inside == [["lifecycle"]]

    @pytest.mark.unit
    def test_handle_thread_is_daemon(self):
        ev = threading.Event()
        handle = run_job(ev.wait, name="daemon-check")
        assert handle.thread.daemon is True
        ev.set()
        _join(handle)


# ============================== 异常路由 ============================== #
class TestErrorRouting:
    @pytest.mark.unit
    def test_on_error_receives_exception_and_job_deregisters(self):
        started = threading.Event()
        caught: list[BaseException] = []

        def work():
            started.set()
            raise ValueError("boom")

        handle = run_job(work, name="err-hook", on_error=caught.append)
        _join(handle)
        assert len(caught) == 1
        assert isinstance(caught[0], ValueError)
        assert str(caught[0]) == "boom"
        assert active_jobs() == []

    @pytest.mark.unit
    def test_without_on_error_logs_exception(self, caplog):
        started = threading.Event()

        def work():
            started.set()
            raise RuntimeError("silent-death")

        with caplog.at_level(logging.ERROR, logger="gui.core.jobs"):
            handle = run_job(work, name="err-log")
            _join(handle)
        errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errs) == 1, f"应恰好一条 ERROR 记录，实际 {[str(r.msg) for r in errs]}"
        assert errs[0].exc_info is not None
        assert errs[0].exc_info[0] is RuntimeError
        assert active_jobs() == []

    @pytest.mark.unit
    def test_on_error_itself_failing_is_logged_and_job_still_deregisters(self, caplog):
        def bad_hook(exc):
            raise KeyError("hook-broken")

        with caplog.at_level(logging.ERROR, logger="gui.core.jobs"):
            handle = run_job(lambda: 1 / 0, name="hook-broken", on_error=bad_hook)
            _join(handle)
        assert any(r.exc_info for r in caplog.records), "on_error 自身崩溃须落日志，不得静默"
        assert active_jobs() == []


# ============================== cancel 透传 ============================== #
class TestCancel:
    @pytest.mark.unit
    def test_cancel_event_passed_to_fn_accepting_cancel(self):
        started = threading.Event()
        received: list[threading.Event] = []

        def work(cancel):
            received.append(cancel)
            started.set()
            cancel.wait(5)  # 协作停止：cancel 置位即返回

        handle = run_job(work, name="cancel-ok")
        assert started.wait(3)
        handle.cancel.set()
        _join(handle)
        assert received and received[0] is handle.cancel

    @pytest.mark.unit
    def test_request_stop_sets_cancel(self):
        started = threading.Event()

        def work(cancel):
            started.set()
            cancel.wait(5)

        handle = run_job(work, name="stop-one")
        assert started.wait(3)
        handle.request_stop()
        _join(handle)

    @pytest.mark.unit
    def test_fn_without_cancel_param_called_plain(self):
        ran: list[int] = []
        handle = run_job(lambda: ran.append(1), name="no-cancel")
        _join(handle)
        assert ran == [1]

    @pytest.mark.unit
    def test_fn_with_var_keyword_receives_cancel(self):
        got: dict[str, object] = {}
        started = threading.Event()

        def work(**kw):
            got.update(kw)
            started.set()

        handle = run_job(work, name="cancel-kwargs")
        assert started.wait(3)
        _join(handle)
        assert got.get("cancel") is handle.cancel


# ============================== request_stop_all 有界 ============================== #
class TestStopAll:
    @pytest.mark.unit
    def test_bounded_wait_and_reports_stuck_jobs_only(self):
        started_coop = threading.Event()
        started_stub = threading.Event()

        def cooperative(cancel):
            started_coop.set()
            cancel.wait(5)

        def stubborn(cancel):
            started_stub.set()
            time.sleep(1.2)  # 无视 cancel 的赖床任务

        ha = run_job(cooperative, name="coop")
        hb = run_job(stubborn, name="stubborn")
        assert started_coop.wait(3) and started_stub.wait(3)

        t0 = time.monotonic()
        stuck = request_stop_all(timeout_s=0.3)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"总预算 0.3s 须有界返回，实测 {elapsed:.2f}s"
        assert stuck == ["stubborn"], "协作任务应退出且不上报，仅赖床者上报"
        _join(hb, timeout_s=4.0)  # 收尾防泄漏
        assert active_jobs() == []

    @pytest.mark.unit
    def test_empty_registry_returns_immediately(self):
        t0 = time.monotonic()
        assert request_stop_all(timeout_s=5.0) == []
        assert time.monotonic() - t0 < 1.0


# ============================== 并发注册表一致性 ============================== #
class TestConcurrency:
    @pytest.mark.unit
    def test_ten_concurrent_jobs_registry_consistency(self):
        barrier = threading.Barrier(11, timeout=5)
        names = [f"job-{i}" for i in range(10)]
        handles = [run_job(lambda: barrier.wait(5), name=n) for n in names]

        barrier.wait(5)  # 10 worker + 主线程同时放行 → 此刻 10 个全部在册

        assert sorted(active_jobs()) == sorted(names)
        for h in handles:
            _join(h)
        assert active_jobs() == []


# ============================== FakeThread 替换接缝 ============================== #
class TestThreadSeam:
    @pytest.mark.unit
    def test_threading_thread_monkeypatch_seam(self, monkeypatch):
        """复刻 tests/test_gui_datamanage_page.py:29-40 的 FakeThread 接缝：
        monkeypatch threading.Thread 后 run_job 必须经替换类建线程（同步执行）。
        """
        daemon_flags: list[object] = []

        class FakeThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._target, self._args, self._kwargs = target, args, kwargs or {}
                self.daemon = daemon
                daemon_flags.append(daemon)

            def start(self):
                if self._target:
                    self._target(*self._args, **self._kwargs)

        monkeypatch.setattr(threading, "Thread", FakeThread)

        ran: list[int] = []
        handle = run_job(lambda: ran.append(1), name="seam")

        assert ran == [1], "同步 start() 应已执行包裹函数"
        assert isinstance(handle.thread, FakeThread), "线程须经 threading.Thread 属性解析创建"
        assert handle.thread.daemon is True
        assert daemon_flags == [True]
        assert active_jobs() == [], "同步执行路径下 finally 自摘除应已完成"

    @pytest.mark.unit
    def test_module_never_imports_thread_class_directly(self):
        """禁止 from threading import Thread——导入期固化引用会击穿接缝。
        AST 判定（非文本扫描，docstring 提及该写法不算违规）。
        """
        import ast

        import gui.core.jobs as jobs_mod

        tree = ast.parse(inspect.getsource(jobs_mod))
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "threading"
        ]
        assert not offenders, f"发现 from threading import：{ast.dump(offenders[0])}"


# ============================== 句柄便捷方法与防御分支 ============================== #
class TestHandleConveniences:
    @pytest.mark.unit
    def test_is_alive_join_request_stop_delegate_to_thread(self):
        started = threading.Event()

        def work(cancel):
            started.set()
            cancel.wait(5)

        handle = run_job(work, name="conv")
        assert started.wait(3)
        assert handle.is_alive() is True
        handle.request_stop()
        handle.join(timeout_s=3.0)
        assert handle.is_alive() is False

    @pytest.mark.unit
    def test_seam_thread_without_join_is_alive_tolerated(self, monkeypatch):
        """替换线程无 join/is_alive 属性（如仓库 FakeThread）：不炸、视为已退出。"""

        class BareThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._t = target

            def start(self):
                if self._t:
                    self._t()

        monkeypatch.setattr(threading, "Thread", BareThread)
        handle = run_job(lambda: None, name="bare")
        assert handle.is_alive() is False
        handle.join(timeout_s=1.0)  # 无 join 属性 → 立即返回，不抛即过
        assert request_stop_all(timeout_s=0.1) == []  # 无 join 属性不炸

    @pytest.mark.unit
    def test_join_raising_runtime_error_tolerated_by_stop_all(self, monkeypatch):
        """request_stop_all 的 join RuntimeError 防御分支：被吞、以注册表为准。"""
        real_thread_cls = threading.Thread  # patch 前捕获真类，供内部真跑自摘除

        class RudeJoinThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._t, self._real = target, None

            def start(self):
                if self._t:
                    self._real = real_thread_cls(target=self._t)
                    self._real.start()  # 真后台执行 → finally 自摘除，注册表不泄漏

            def join(self, timeout=None):
                raise RuntimeError("cannot join")

        monkeypatch.setattr(threading, "Thread", RudeJoinThread)
        started = threading.Event()

        def work(cancel):  # 参数名必须为 cancel（run_job 按名内省透传）
            started.set()
            time.sleep(0.5)  # 不响应 cancel：确保 stop_all 快照时仍在册（时序确定）

        run_job(work, name="rude")
        assert started.wait(3)
        result = request_stop_all(timeout_s=0.2)  # join 抛 RuntimeError → 不得外泄
        assert result == ["rude"]  # join 失败且线程未退出 → 仍在册（收紧自 isinstance）
        for _ in range(100):  # 0.5s sleep 到期 → 自摘除，注册表不泄漏
            if not active_jobs():
                break
            time.sleep(0.05)
        assert active_jobs() == []

    @pytest.mark.unit
    def test_start_failure_rolls_back_registration(self, monkeypatch):
        """thread.start() 自身抛异常（如 OS 线程耗尽）：异常上抛且注册表零泄漏。"""

        class StartFailThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._t = target

            def start(self):
                raise RuntimeError("can't start new thread")

        monkeypatch.setattr(threading, "Thread", StartFailThread)
        with pytest.raises(RuntimeError, match="can't start new thread"):
            run_job(lambda: None, name="doomed")
        assert active_jobs() == []  # 登记条目必须随 start 失败回滚

    @pytest.mark.unit
    def test_stop_all_with_registered_no_join_replacement_thread(self, monkeypatch):
        """在册（start 未执行 target）且无 join 属性的替换线程：跳过 join、如实上报仍在册。"""

        class SilentThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._t = target

            def start(self):  # 不执行 target → 任务永不完成 → 永在册
                pass

        monkeypatch.setattr(threading, "Thread", SilentThread)
        run_job(lambda: None, name="silent")
        try:
            assert active_jobs() == ["silent"]
            result = request_stop_all(timeout_s=0.1)  # 无 join 属性 → 跳过等待不炸
            assert result == ["silent"]
        finally:
            # SilentThread 永不执行 target → 条目永不自摘除；手动清出模块级注册表
            # 防污染后续用例（nested 用例断言注册表仅含自身）
            import gui.core.jobs as jobs_mod
            with jobs_mod._lock:
                for jid, h in list(jobs_mod._jobs.items()):
                    if h.name == "silent":
                        jobs_mod._jobs.pop(jid)

    @pytest.mark.unit
    def test_nested_request_stop_all_from_inside_job_does_not_join_self(self):
        """job 内部调用 request_stop_all：不得 join 自己（RuntimeError 死路）。"""
        result_box: dict[str, list[str]] = {}

        def work(cancel):
            result_box["stuck"] = request_stop_all(timeout_s=0.2)

        handle = run_job(work, name="self-stop")
        _join(handle)
        assert result_box["stuck"] == ["self-stop"], "自身在册须上报（未退出）"
        assert active_jobs() == []

    @pytest.mark.unit
    def test_non_introspectable_callable_called_plain(self):
        """__signature__ 读取抛 TypeError 的可调用对象 → 按无参调用，不炸。"""
        ran: list[int] = []
        done = threading.Event()

        class Weird:
            def __call__(self):
                ran.append(1)
                done.set()

            @property
            def __signature__(self):
                raise TypeError("no signature")

        handle = run_job(Weird(), name="weird")
        assert done.wait(3)
        handle.join(timeout_s=2.0)
        assert ran == [1]


# ============================== 入参校验 ============================== #
class TestValidation:
    @pytest.mark.unit
    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            run_job(lambda: None, name="")

    @pytest.mark.unit
    def test_non_callable_fn_rejected(self):
        with pytest.raises(TypeError):
            run_job("not-callable", name="bad")
