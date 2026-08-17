"""后台任务统一调度器（W15-J1；架构审查 v2 P2-1 抽象落地）。

P2-1 证据：裸 threading.Thread 10 处（data_manage:368/474、deploy:191、
eval_:388、flaw_gen:210、label:569/654/686、predict:301/419）+ 三套线程模型
并存（TrainWorker(QThread) / 裸 Thread / ThumbnailTask(QRunnable)），
grep run_job/PageJob = 0。本模块提供三者中最通用的"裸 Thread"一类的
统一替代：注册表登记 + 协作取消 + 异常路由 + 有界停机。

设计契约（W15 阶段二 J2/J3/J4 按此消费）：
    handle = run_job(work, name="op", on_error=hook)
    active_jobs()               -> list[str]        运行中任务名（线程安全）
    request_stop_all(timeout_s) -> list[str]        停不下来的任务名

约束：
1. 零 Qt 依赖——只 threading + logging + 标准库，gui/core 下但任意层可测、
   可在无 PySide6 环境消费（对照 thread_bridge.py 只封装 invokeMethod、
   不封装生命周期）。
2. 线程必须经 ``threading.Thread(...)`` 调用期属性解析创建——不得
   ``from threading import Thread``，否则击穿既有 FakeThread monkeypatch
   接缝（tests/test_gui_datamanage_page.py:29-40 等 10 个测试文件依赖）。
   同时只传 target/daemon 关键字（FakeThread 构造器仅接受这四种参数），
   任务名存 JobHandle/注册表，不进 Thread(name=...)。
"""
from __future__ import annotations

import inspect
import itertools
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ErrorHandler = Callable[[Exception], None]


@dataclass(frozen=True)
class JobHandle:
    """run_job 返回句柄：调用方持有的任务唯一视角。

    Attributes:
        job_id: 注册表内部序号（同名任务可并存，靠它区分）。
        name: 任务名（调用方给定，用于 active_jobs()/停机报告）。
        cancel: 协作取消事件——fn 若声明 cancel 参数则收到同一实例；
            页面可随时置位，任务自行在检查点响应。
        thread: 承载线程（真 threading.Thread，或测试替换的 FakeThread）。
    """

    job_id: int
    name: str
    cancel: threading.Event
    thread: Any

    def request_stop(self) -> None:
        """置位取消事件（协作停止请求，不强杀）。"""
        self.cancel.set()

    def is_alive(self) -> bool:
        """线程是否仍在运行（替换线程无 is_alive 时视为已退出）。"""
        check = getattr(self.thread, "is_alive", None)
        return bool(check()) if callable(check) else False

    def join(self, timeout_s: Optional[float] = None) -> None:
        """有界/无限 join（替换线程无 join 时立即返回）。"""
        do_join = getattr(self.thread, "join", None)
        if callable(do_join):
            do_join(timeout_s)


# 注册表：job_id -> 句柄；_lock 保护全部读写（含序号分配）
_jobs: "dict[int, JobHandle]" = {}
_lock = threading.RLock()
_seq = itertools.count(1)


def _accepts_cancel(fn: Callable[..., Any]) -> bool:
    """fn 是否可接收 cancel 关键字参数（具名 cancel 或 **kwargs）。"""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False  # 不可内省的可调用对象（部分内置/ctypes）→ 按无参调用
    param = sig.parameters.get("cancel")
    if param is not None and param.kind is not inspect.Parameter.POSITIONAL_ONLY:
        return True
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )


def run_job(
    fn: Callable[..., Any],
    *,
    name: str,
    on_error: Optional[ErrorHandler] = None,
) -> JobHandle:
    """在 daemon 线程执行 fn，全程登记注册表，返回可取消句柄。

    生命周期：注册 → 执行（fn 声明 cancel 参数则透传同一 threading.Event）
    → 异常路由（有 on_error 则调 on_error(exc)，无则 logger.exception）
    → finally 注册表自摘除。

    Args:
        fn: 无参或单 cancel 关键字参数的可调用对象（worker 线程执行）。
        name: 任务名（空串拒绝；同名任务可并存，靠 job_id 区分）。
        on_error: 异常回调，收到 Exception 本体；页面自行决定是否经
            invoke_main 回 UI（本模块不引入 Qt，不做转发）。

    Returns:
        JobHandle（至少含 .cancel Event 与 .thread）。

    Raises:
        ValueError: name 为空。
        TypeError: fn 不可调用。
    """
    if not name:
        raise ValueError("run_job: name 不能为空")
    if not callable(fn):
        raise TypeError(f"run_job: fn 不可调用（got {type(fn).__name__}）")

    cancel = threading.Event()

    def _runner() -> None:
        try:
            if _accepts_cancel(fn):
                fn(cancel=cancel)
            else:
                fn()
        except Exception as exc:  # noqa: BLE001 —— 路由点，必须全收
            if on_error is not None:
                try:
                    on_error(exc)
                except Exception:  # noqa: BLE001 —— 回调崩溃只落日志不外泄
                    logger.exception(
                        "后台任务 %s 的 on_error 处理器自身抛异常", name
                    )
            else:
                logger.exception("后台任务 %s 异常退出", name)
        finally:
            with _lock:
                _jobs.pop(job_id, None)

    # 接缝关键（见模块 docstring 约束 2）：调用期属性解析 + 仅 target/daemon
    thread = threading.Thread(target=_runner, daemon=True)

    with _lock:
        job_id = next(_seq)
        handle = JobHandle(job_id=job_id, name=name, cancel=cancel, thread=thread)
        _jobs[job_id] = handle  # 先登记后启动：start 返回即可被 active_jobs 观测

    try:
        thread.start()
    except BaseException:
        # start 自身失败（如 OS 线程耗尽）：回滚登记，否则条目永久泄漏且
        # request_stop_all 将永远上报该名字（W15 验证员建议，W16 落地）
        with _lock:
            _jobs.pop(job_id, None)
        raise
    return handle


def active_jobs() -> "list[str]":
    """当前在册任务名列表（线程安全快照，注册先后序，同名可重复）。"""
    with _lock:
        return [h.name for h in _jobs.values()]


def request_stop_all(timeout_s: float = 5.0) -> "list[str]":
    """对全部在册任务置位 cancel 并有界等待退出，返回未退出者名字。

    timeout_s 是所有 join 共享的总预算（非单线程预算）：到点即返回，
    剩余任务不阻塞、不再等待。仍在注册表中的任务即"未退出"（任务退出
    时在 finally 中自摘除）。兼容测试替换线程（无 join/is_alive 属性时
    跳过对应操作，以注册表状态为准）。

    Args:
        timeout_s: 总等待预算秒数（负值按 0 处理）。

    Returns:
        超预算仍未退出的任务名列表（快照序）。
    """
    with _lock:
        snapshot = list(_jobs.values())

    for handle in snapshot:
        handle.cancel.set()

    deadline = time.monotonic() + max(0.0, timeout_s)
    for handle in snapshot:
        thread = handle.thread
        if thread is threading.current_thread():
            continue  # 嵌套 run_job 场景：不能 join 自己，直接按在册上报
        remaining = deadline - time.monotonic()
        do_join = getattr(thread, "join", None)
        if callable(do_join):
            try:
                do_join(max(0.0, remaining))
            except RuntimeError:
                pass  # 线程未 start 等异常；以注册表状态为准继续收尾

    with _lock:
        still_registered = {id(h) for h in _jobs.values()}
    return [h.name for h in snapshot if id(h) in still_registered]


__all__ = ["JobHandle", "run_job", "active_jobs", "request_stop_all"]
