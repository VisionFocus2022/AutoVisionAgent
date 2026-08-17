"""shell.closeEvent 退出前审计刷盘（W12-R3）：accept 路径必须显式 flush 审计日志。

core.audit_logger 缓冲未满 _buffer_max(100) 时不落盘——正常退出前若不显式
flush，尾部审计事件会随进程退出丢失。离屏验证（无 worker → 直达 accept 分支）：
① flush 必须被调用；② flush 抛异常不得阻断退出（warning 吞掉）。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")  # 无 PySide6 则跳过本模块

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def win(qapp):
    from gui.core.shell import MainWindow

    w = MainWindow("AuditFlushTest")
    yield w
    w.close()


@pytest.mark.unit
def test_close_event_flushes_audit_logger_before_accept(win, monkeypatch):
    """无 worker 时 closeEvent 直达 accept 分支，且退出前审计日志必须 flush。"""
    import core.audit_logger as audit_mod

    flushed: list[bool] = []

    class _SpyAudit:
        def flush(self) -> None:
            flushed.append(True)

    monkeypatch.setattr(audit_mod, "get_audit_logger", lambda *a, **k: _SpyAudit())

    ev = QCloseEvent()
    win.closeEvent(ev)
    assert flushed == [True]  # accept 前必须显式刷盘审计缓冲
    assert ev.isAccepted() is True


@pytest.mark.unit
def test_close_event_audit_flush_failure_still_accepts(win, monkeypatch, caplog):
    """审计 flush 抛异常不得阻断退出：吞掉并 logger.warning。"""
    import core.audit_logger as audit_mod

    def _boom(*a, **k):
        raise RuntimeError("audit disk full")

    monkeypatch.setattr(audit_mod, "get_audit_logger", _boom)

    ev = QCloseEvent()
    with caplog.at_level("WARNING", logger="gui.core.shell"):
        win.closeEvent(ev)
    assert ev.isAccepted() is True  # 审计异常不得吞掉退出
    assert any("审计" in r.message for r in caplog.records)  # 必须 warning 留痕
