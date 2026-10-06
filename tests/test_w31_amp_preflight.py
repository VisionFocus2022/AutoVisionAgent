"""W31/W1-4 AMP 预检测试（真线程模式重写）。

W1-4（PRD docs/prd-w1-4-w1-5-wave1-tail.md）后预检在 TrainWorker 线程：
- AC-4①预检线程≠主线程，_start_training 即刻返回
- AC-4②预检失败 → fit 收到 amp=False + 状态"AMP 预检失败" + chk_amp 取消
- AC-4③预检成功 → amp=True 保持
"""
from __future__ import annotations

import threading
import time

import pytest

from core.interfaces_supervised import TaskType as _TaskType


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Artifact:
    task = _TaskType.DET
    config = None
    weights_path = ""
    metrics = {}
    epochs_completed = 1
    best_metric = 0.0


class _Trainer:
    """fit 即回：捕获传入 cfg（amp 回退断言用）。"""

    def __init__(self):
        self.captured = None

    def fit(self, cfg, progress, should_stop):
        self.captured = cfg
        progress(1.0, {"loss": 0.5})
        return _Artifact()


def _make_page(monkeypatch, preflight_result):
    """真 TrainWorker 页面；预检结果注入并记录调用线程。"""
    from gui.pages.train import page as train_mod

    monkeypatch.setattr(train_mod.TrainPage, "_confirm_simulated",
                        lambda self: True)
    page = train_mod.TrainPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    recorder = {"thread": None, "calls": 0}

    def _fake_preflight(device):
        recorder["calls"] += 1
        recorder["thread"] = threading.get_ident()
        return preflight_result

    import models.supervised.amp_preflight as ap

    monkeypatch.setattr(ap, "amp_preflight", _fake_preflight)
    trainer = _Trainer()
    monkeypatch.setattr(page, "_make_trainer", lambda cfg: trainer)
    return page, trainer, recorder


def _wait_finish(qapp, page, timeout=15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()  # 跨线程排队信号（finished/清理链）需事件泵
        if getattr(page, "_worker", None) is None:
            return
        time.sleep(0.1)
    raise AssertionError("训练线程未在时限内收尾")


@pytest.mark.unit
def test_amp_preflight_fails_in_worker(qapp, monkeypatch):
    """AC-4②：预检失败（worker 线程）→ amp=False/状态/取消勾选。"""
    page, trainer, recorder = _make_page(monkeypatch, (False, "fp16 非有限"))
    page.chk_amp.setChecked(True)
    t0 = time.time()
    page._start_training()
    assert time.time() - t0 < 0.5, "_start_training 应即刻返回（预检在 worker）"
    _wait_finish(qapp, page)
    assert recorder["calls"] == 1
    assert recorder["thread"] != threading.get_ident(), "预检应跑在 worker 线程"
    assert trainer.captured.amp is False, "fit 应收到 amp=False 回退"
    assert page.chk_amp.isChecked() is False
    assert any(t == "AMP 预检失败，已回退 FP32" for t, _ in page._msgs)
    assert any(t == "训练完成" for t, _ in page._msgs)


@pytest.mark.unit
def test_amp_preflight_ok_keeps_amp(qapp, monkeypatch):
    """AC-4③：预检成功 → amp=True 保持、无回退状态。"""
    page, trainer, recorder = _make_page(monkeypatch, (True, "ok"))
    page.chk_amp.setChecked(True)
    page._start_training()
    _wait_finish(qapp, page)
    assert recorder["calls"] == 1
    assert trainer.captured.amp is True
    assert not any("AMP" in t for t, _ in page._msgs), "成功不应有 AMP 警告"
    assert page.chk_amp.isChecked() is True


@pytest.mark.unit
def test_amp_disabled_skips_preflight(qapp, monkeypatch):
    """amp 未勾选 → 预检零调用（cpu/lite 路径不打扰）。"""
    page, trainer, recorder = _make_page(monkeypatch, (True, "ok"))
    page.chk_amp.setChecked(False)
    page._start_training()
    _wait_finish(qapp, page)
    assert recorder["calls"] == 0
    assert trainer.captured.amp is False
