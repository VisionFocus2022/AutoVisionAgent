"""shell.closeEvent 退出守卫与生命周期（W15-J4：P2-2/P2-3）。

P2-2 证据（docs/AutoVisionAgent-架构解析与优化方案-v2.md:253-254）：
旧守卫仅探测 _worker（全 gui 唯一赋值点 train/page.py）与 _btn_batch——
predict 页按钮属性名实为 btn_batch（predict/page.py:128/:384，无下划线）
→ getattr(widget,'_btn_batch') 恒 None → 批量推理进行中退出无确认弹窗；
10 处裸 daemon 线程（inline start、线程对象无引用）对守卫完全不可见。
P2-3 证据（:256-257）：确认 Yes 后仅 registry.clear_cache() 即 accept——
不 stop/wait TrainWorker(QThread)（"QThread: Destroyed while thread is
still running" 确定性崩溃路径）、不清空/等待两个缩略图 QThreadPool
（data_manage/page.py:61、label/page.py:220）。

本模块经生产 run_job 启真实注册任务离屏验证：
① 注册表任务在册 → 必弹确认框且文案含任务名；No → event.ignore()；
② Yes → event.accept() 且 jobs.request_stop_all 被调（有界超时入参），
   join 在 closeEvent 内完成、注册表清空（历史 bug 位根除：属性名探测
   不再是唯一真相源）；
③ predict 批量场景（btn_batch 命名、无 _btn_batch）双路覆盖：注册表
   路径 + 按钮禁用约定路径（btn_batch 命名也识别）均拦截；
④ 确认后 TrainWorker stop() + wait(有界 ms) 与缩略图池 clear() +
   waitForDone(有界 ms) 被调（全部等待有界，不卡 UI）；
⑤ 引擎缓存清理 → 审计 flush → accept 原顺序保留（特征化守卫）。
"""
from __future__ import annotations

import logging
import os
import threading
import time

import pytest

pytest.importorskip("PySide6")  # 无 PySide6 则跳过本模块

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QMessageBox,
    QPushButton,
    QWidget,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_native_dialogs(monkeypatch):
    """offscreen 安全网：未被测例显式打桩的原生确认框一律返回 No。

    覆盖断言失败中途退出的场景——win teardown close 时 monkeypatch 若已
    撤销且注册表仍有任务在册，会真弹 QMessageBox 永久阻塞。
    """
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )


@pytest.fixture(autouse=True)
def _drain_jobs():
    """注册表是模块级真相源：每例收尾强制排空，防任务跨用例泄漏
    （泄漏会让其他测试文件的 closeEvent 走确认分支）。"""
    from gui.core import jobs

    yield
    jobs.request_stop_all(timeout_s=1.0)


@pytest.fixture
def win(qapp):
    from gui.core.shell import MainWindow

    w = MainWindow("ExitGuardTest")
    yield w
    # teardown 先中和页级"活动"标记再 close：否则 monkeypatch 撤销后
    # closeEvent 弹真框（offscreen 永久阻塞）
    for page in w._pages.values():
        if getattr(page, "_worker", None) is not None:
            page._worker = None
        for attr in ("_btn_batch", "btn_batch"):
            btn = getattr(page, attr, None)
            if btn is not None and not btn.isEnabled():
                btn.setEnabled(True)
    w.close()


# ============================== 桩与工具 ============================== #


def _sleeper(cancel: threading.Event, poll_s: float = 0.02) -> None:
    """协作取消长任务：cancel 置位后 ~poll_s 内退出。"""
    while not cancel.is_set():
        time.sleep(poll_s)


def _close_evt() -> QCloseEvent:
    ev = QCloseEvent()
    assert ev.isAccepted() is True  # 默认 accepted；ignore/accept 才有分辨力
    return ev


def _patch_question(monkeypatch, reply, captured=None):
    """打桩确认框：记录 (title, text) 并返回指定按钮。"""
    def _question(parent, title, text, *args, **kwargs):
        if captured is not None:
            captured.append((title, text))
        return reply

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_question))


# ============================== P2-2：注册表真相源 ============================== #


@pytest.mark.unit
def test_close_event_registry_job_no_ignores_with_task_name(win, monkeypatch):
    """注册表任务在册 → 弹确认框（文案含任务名）；No → 不得退出。

    RED（旧守卫）：run_job 任务对逐页 getattr 探测不可见 → 无弹窗直接
    accept，后台任务静默被杀。
    """
    from gui.core.jobs import active_jobs, run_job

    handle = run_job(_sleeper, name="守卫探针-训练模拟")
    assert active_jobs() == ["守卫探针-训练模拟"]  # 前置：任务确在册

    captured: list = []
    _patch_question(monkeypatch, QMessageBox.StandardButton.No, captured)

    ev = _close_evt()
    win.closeEvent(ev)
    assert captured, "注册表任务在册必须弹确认框"
    assert any("守卫探针-训练模拟" in t for _, t in captured)  # 文案含任务名
    assert ev.isAccepted() is False  # No → event.ignore()

    handle.request_stop()
    handle.join(1.0)  # 防泄漏到后续用例


@pytest.mark.unit
def test_close_event_registry_job_yes_stops_all_and_accepts(win, monkeypatch):
    """Yes → accept 且 request_stop_all 被调（有界超时入参，join 收敛）。"""
    import gui.core.jobs as jobs_mod
    from gui.core.jobs import active_jobs, run_job

    handle = run_job(_sleeper, name="守卫探针-Yes停机")

    calls: list[float] = []
    real_stop_all = jobs_mod.request_stop_all

    def _spy(timeout_s: float = 5.0):
        calls.append(timeout_s)
        return real_stop_all(timeout_s)

    monkeypatch.setattr(jobs_mod, "request_stop_all", _spy)
    _patch_question(monkeypatch, QMessageBox.StandardButton.Yes)

    ev = _close_evt()
    win.closeEvent(ev)
    assert ev.isAccepted() is True            # 确认 → 放行
    assert calls and 0 < calls[0] <= 5.0      # 有界停机预算（非无限等待）
    assert handle.cancel.is_set()             # request_stop_all 真跑过
    assert active_jobs() == []                # join 在 closeEvent 内完成


# ============================== P2-2：predict 批量历史 bug 位 ============================== #


@pytest.mark.unit
def test_close_event_predict_batch_via_registry(win, monkeypatch):
    """predict 批量场景经注册表路径覆盖：属性名失配根除。

    页面仅持有 predict 页真实属性形状（_batch_cancel + btn_batch 禁用，
    无 _btn_batch、无 _worker）——旧守卫两路探测全部失配。
    """
    from gui.core.jobs import run_job

    handle = run_job(_sleeper, name="predict批量推理")

    page = QWidget()
    page._batch_cancel = False
    page.btn_batch = QPushButton("批量推理")  # predict 页真名（无下划线）
    page.btn_batch.setEnabled(False)          # 批量进行中约定：按钮禁用
    win.add_page("predict", "i", "P", page)

    captured: list = []
    _patch_question(monkeypatch, QMessageBox.StandardButton.No, captured)

    ev = _close_evt()
    win.closeEvent(ev)
    assert ev.isAccepted() is False  # 批量推理中 → No 必须拦下退出
    assert any("predict批量推理" in t for _, t in captured)

    handle.request_stop()
    handle.join(1.0)


@pytest.mark.unit
def test_close_event_predict_btn_batch_naming_alone_blocks_exit(win, monkeypatch):
    """纯按钮约定路径（无注册任务）：btn_batch（无下划线）禁用也算活动。

    RED（旧守卫）：只认 _btn_batch → predict 页 getattr 恒 None → 批量
    推理中退出无确认。
    """
    page = QWidget()
    page._batch_cancel = False
    page.btn_batch = QPushButton("批量推理")
    page.btn_batch.setEnabled(False)
    win.add_page("predict", "i", "P", page)

    called: list = []
    _patch_question(monkeypatch, QMessageBox.StandardButton.No, called)

    ev = _close_evt()
    win.closeEvent(ev)
    assert called, "btn_batch 禁用（predict 命名）必须触发确认框"
    assert ev.isAccepted() is False


# ============================== P2-3：确认后有界停机 ============================== #


class _FakeTrainWorker:
    """训练 QThread 桩：记录 stop/wait 调用（wait 模拟协作停止完成）。"""

    def __init__(self, running: bool = True) -> None:
        self._running = running
        self.stop_calls: list[bool] = []
        self.wait_ms: list = []

    def isRunning(self) -> bool:
        return self._running

    def stop(self) -> None:
        self.stop_calls.append(True)

    def wait(self, msecs=None) -> bool:
        self.wait_ms.append(msecs)
        self._running = False  # 模拟协作停止完成
        return True


class _FakePool:
    """缩略图 QThreadPool 桩：记录 clear/waitForDone 调用。"""

    def __init__(self) -> None:
        self.clear_calls: list[bool] = []
        self.wait_ms: list = []

    def clear(self) -> None:
        self.clear_calls.append(True)

    def waitForDone(self, msecs=None) -> bool:
        self.wait_ms.append(msecs)
        return True


@pytest.mark.unit
def test_close_event_yes_stops_qthread_and_pools_bounded(win, monkeypatch):
    """确认退出后：QThread stop()+wait(有界 ms)、缩略图池 clear()+waitForDone(有界 ms)。"""
    from gui.core.shell import _EXIT_POOL_WAIT_MS, _EXIT_WORKER_WAIT_MS

    worker = _FakeTrainWorker(running=True)
    idle_worker = _FakeTrainWorker(running=False)  # 不在跑 → 不得被 stop
    pool = _FakePool()
    page_w = QWidget()
    page_w._worker = worker
    page_idle = QWidget()
    page_idle._worker = idle_worker
    page_pool = QWidget()
    page_pool._thumb_pool = pool
    win.add_page("train", "i", "T", page_w)
    win.add_page("idle", "i", "I", page_idle)
    win.add_page("thumbs", "i", "D", page_pool)

    _patch_question(monkeypatch, QMessageBox.StandardButton.Yes)

    ev = _close_evt()
    win.closeEvent(ev)

    assert ev.isAccepted() is True
    assert worker.stop_calls == [True]                 # 协作停止已请求
    assert worker.wait_ms == [_EXIT_WORKER_WAIT_MS]    # 有界等待（常量上限）
    assert 0 < worker.wait_ms[0] <= 3000                # 总量级约束
    assert idle_worker.stop_calls == []                 # 空闲 worker 不打扰
    assert pool.clear_calls == [True]                   # 排队任务丢弃
    assert pool.wait_ms == [_EXIT_POOL_WAIT_MS]         # 有界池等待
    assert 0 <= pool.wait_ms[0] <= 3000


# ================ W18（TASK-001 / P2-3 退出链）：停机超时告警 ================ #


@pytest.mark.unit
def test_close_event_worker_stop_timeout_logs_warning(win, monkeypatch, caplog):
    """W18（RED）：确认退出后训练线程 stop()/wait(有界 ms) 超时仍 isRunning →
    不得静默 continue，须落 warning——含"将随进程退出被强制终止、可能丢失
    未保存进度"语义并引用 _EXIT_WORKER_WAIT_MS 常量值。"""
    from gui.core.shell import _EXIT_WORKER_WAIT_MS

    class _StubbornWorker(_FakeTrainWorker):
        """顽固 worker：wait() 返回超时且 isRunning 恒 True（不协作停止）。"""

        def wait(self, msecs=None) -> bool:
            self.wait_ms.append(msecs)
            return False  # 超时：_running 不翻转

    stubborn = _StubbornWorker(running=True)
    page_w = QWidget()
    page_w._worker = stubborn
    win.add_page("train", "i", "T", page_w)

    _patch_question(monkeypatch, QMessageBox.StandardButton.Yes)

    with caplog.at_level(logging.WARNING, logger="gui.core.shell"):
        ev = _close_evt()
        win.closeEvent(ev)

    assert ev.isAccepted() is True                 # 告警不阻断退出
    assert stubborn.stop_calls == [True]           # 停止请求仍发出
    assert stubborn.wait_ms == [_EXIT_WORKER_WAIT_MS]
    warnings = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any(
        "强制终止" in m and "未保存" in m and str(_EXIT_WORKER_WAIT_MS) in m
        for m in warnings
    ), f"stop/wait 超时必须留痕（含丢进度语义与预算值），got={warnings}"


# ============================== 原顺序保留（特征化守卫） ============================== #


@pytest.mark.unit
def test_close_event_keeps_cache_then_flush_order(win, monkeypatch):
    """确认退出路径原顺序：引擎缓存清理 → 审计 flush → accept（W12 行为保持）。"""
    import core.audit_logger as audit_mod
    import models.supervised.registry as reg_mod
    from gui.core.jobs import run_job

    handle = run_job(_sleeper, name="顺序探针")
    order: list[str] = []

    class _OrderingReg:
        def clear_cache(self) -> None:
            order.append("clear_cache")

    class _OrderingAudit:
        def flush(self) -> None:
            order.append("flush")

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _OrderingReg())
    monkeypatch.setattr(audit_mod, "get_audit_logger", lambda *a, **k: _OrderingAudit())
    _patch_question(monkeypatch, QMessageBox.StandardButton.Yes)

    ev = _close_evt()
    win.closeEvent(ev)
    assert ev.isAccepted() is True
    assert order == ["clear_cache", "flush"]  # 既有顺序不得倒置

    if handle.cancel.is_set():
        handle.join(1.0)  # closeEvent 已停机 → 收尾
    else:
        handle.request_stop()
        handle.join(1.0)
