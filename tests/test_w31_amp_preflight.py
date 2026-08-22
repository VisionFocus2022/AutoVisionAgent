"""W31（W26 计划 P2）：AMP 预检——训练前 cuda 侧 fp16 前向+反向有限性探针。

背景：SKolpha 打包 checkamp.pt 资产方案被弃用（随包资产 +2MB 且黑盒）；
2 行 autocast 往返等价且诚实。失败=警告+回退 FP32；cpu/lite 静默跳过。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ============================== 1. 探针纯函数 ============================== #


@pytest.mark.unit
def test_amp_preflight_cpu_skips():
    """cpu / lite（CPU torch）：静默跳过——(True, "skip")，不触 GPU 探测。"""
    from models.supervised.amp_preflight import amp_preflight

    ok, reason = amp_preflight("cpu")
    assert ok is True and reason == "skip"


@pytest.mark.unit
def test_amp_preflight_cuda_exception_returns_false_with_reason(monkeypatch):
    """cuda 侧探针异常 → (False, 原因含探针失败)——不静默不崩。"""
    import torch

    from models.supervised import amp_preflight as amp_mod

    monkeypatch.setattr(amp_mod, "resolve_device", lambda d: "cuda")

    def _boom(*a, **k):
        raise RuntimeError("cuda probe exploded")

    monkeypatch.setattr(torch, "autocast", _boom)
    ok, reason = amp_mod.amp_preflight("cuda")
    assert ok is False
    assert "探针失败" in reason and "cuda probe exploded" in reason


@pytest.mark.unit
def test_amp_preflight_cuda_nonfinite_grad_returns_false(monkeypatch):
    """反向梯度非有限 → (False, 原因含非有限)。"""
    import torch

    from models.supervised import amp_preflight as amp_mod

    monkeypatch.setattr(amp_mod, "resolve_device", lambda d: "cuda")

    class _FalseAll:
        def all(self):
            return self

        def item(self):
            return False

    monkeypatch.setattr(torch, "isfinite", lambda t: _FalseAll())
    ok, reason = amp_mod.amp_preflight("cuda")
    assert ok is False
    assert "非有限" in reason


# ============================== 2. 训练页接线 ============================== #


def _wire_train_page(monkeypatch, preflight_result):
    """构造训练页并注入预检结果 + 假 TrainWorker 捕获 cfg。"""
    from gui.pages.train import page as train_mod
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    page.chk_amp.setChecked(True)
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))

    captured = []
    monkeypatch.setattr(train_mod, "amp_preflight", lambda d: preflight_result)
    monkeypatch.setattr(TrainPage, "_make_trainer", lambda self, cfg: object())

    class _Sig:
        def connect(self, *a, **k):
            pass

    class _FakeWorker:
        progress = _Sig()
        finished_sig = _Sig()
        failed = _Sig()
        finished = _Sig()

        def __init__(self, trainer, cfg):
            captured.append(cfg)

        def start(self):
            pass

    monkeypatch.setattr(train_mod, "TrainWorker", _FakeWorker)
    return page, msgs, captured


@pytest.mark.unit
def test_train_page_amp_failure_warns_and_falls_back(qapp, monkeypatch):
    """预检失败 → 状态栏警告 + 训练配置回退 FP32 + 复选框即时反映。"""
    page, msgs, captured = _wire_train_page(monkeypatch, (False, "fp16 非有限"))
    page._start_training()

    assert any("回退" in t or "回退" in a for t, a in msgs), msgs
    assert captured and captured[0].amp is False, "训练配置必须回退 amp=False"
    assert page.chk_amp.isChecked() is False


@pytest.mark.unit
def test_train_page_amp_ok_keeps_amp(qapp, monkeypatch):
    """预检通过/跳过 → amp 保持，无警告。"""
    page, msgs, captured = _wire_train_page(monkeypatch, (True, "ok"))
    page._start_training()

    assert captured and captured[0].amp is True
    assert not any("回退" in t or "回退" in a for t, a in msgs)
