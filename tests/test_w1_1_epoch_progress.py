"""W1-1 训练逐轮进度与可中断测试（PRD docs/prd-w1-1-epoch-progress.md）。

- AC-1 适配器：on_fit_epoch_end 注册 → cb 收到 {epoch,total,loss,eta_s}；
  cb 未设不注册。
- AC-2 停止：request_stop 后回调置 trainer.stop=True。
- AC-3 页面：槽更新 bar/chart/lbl；emit 经 invoke_main 派发。
"""
from __future__ import annotations

import pytest

from core.interfaces_supervised import TaskType, TrainConfig
from models.supervised.engines.seg_yolo import SegYoloEngine


class _FakeTrainer:
    def __init__(self, epoch, epochs, loss):
        self.epoch, self.epochs, self.loss = epoch, epochs, loss
        self.stop = False


class _FakeYOLO:
    callbacks: dict = {}
    last_kwargs: dict = {}

    def __init__(self, model=None):
        self.trainer = None
        _FakeYOLO.callbacks = {}

    def add_callback(self, event, fn):
        _FakeYOLO.callbacks[event] = fn

    def train(self, **kwargs):
        _FakeYOLO.last_kwargs = kwargs
        self.trainer = _FakeTrainer(2, 100, 3.5)  # 第 3 轮结束态

    def val(self):
        raise RuntimeError("no val")  # AC-1 不关心指标提取


def _cfg(tmp_path, n=2):
    root = tmp_path / "yolo"
    (root / "labels" / "train").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / "labels" / "train" / f"i{i}.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    y = root / "data.yaml"
    y.write_text("path: x\ntrain: t\nval: v\nnc: 1\nnames: {0: d}\n")
    return TrainConfig(task=TaskType.SEG, epochs=5, data_yaml=str(y),
                       amp=False, device="cpu")


@pytest.mark.unit
class TestAc1AdapterProgressHook:
    def test_callback_registered_and_fires(self, monkeypatch, tmp_path):
        monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)
        engine = SegYoloEngine()
        got: list[dict] = []
        engine.set_progress_callback(got.append)
        engine.train_epoch(1, _cfg(tmp_path))
        assert "on_fit_epoch_end" in _FakeYOLO.callbacks, "应注册轮回调"
        _FakeYOLO.callbacks["on_fit_epoch_end"](_FakeTrainer(2, 100, 3.5))
        assert len(got) == 1
        info = got[0]
        assert info["epoch"] == 3 and info["total"] == 100
        assert info["loss"] == pytest.approx(3.5)
        assert info["eta_s"] >= 0

    def test_no_callback_no_registration(self, monkeypatch, tmp_path):
        monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)
        engine = SegYoloEngine()
        engine.train_epoch(1, _cfg(tmp_path))
        assert _FakeYOLO.callbacks == {}, "未设 cb 不应注册"


@pytest.mark.unit
class TestAc2StopBreaksLoop:
    def test_request_stop_sets_trainer_stop(self, monkeypatch, tmp_path):
        monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)
        engine = SegYoloEngine()
        engine.set_progress_callback(lambda d: None)
        engine.train_epoch(1, _cfg(tmp_path))
        engine.request_stop()
        t = _FakeTrainer(4, 100, 2.0)
        _FakeYOLO.callbacks["on_fit_epoch_end"](t)
        assert t.stop is True, "停止请求应置 trainer.stop 破环"

    def test_no_stop_request_leaves_loop(self, monkeypatch, tmp_path):
        monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)
        engine = SegYoloEngine()
        engine.set_progress_callback(lambda d: None)
        engine.train_epoch(1, _cfg(tmp_path))
        t = _FakeTrainer(4, 100, 2.0)
        _FakeYOLO.callbacks["on_fit_epoch_end"](t)
        assert t.stop is False


@pytest.mark.unit
class TestAc3PageWiring:
    @pytest.fixture(scope="class")
    def qapp(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def test_slot_updates_bar_chart_lbl(self, qapp, monkeypatch):
        from gui.pages.train import page as train_mod

        monkeypatch.setattr(train_mod, "TrainWorker", type("W", (), {}))
        monkeypatch.setattr(train_mod.TrainPage, "_confirm_simulated",
                            lambda self: True)
        page = train_mod.TrainPage()
        page._on_epoch_progress_ui({"epoch": 30, "total": 100, "loss": 0.7,
                                    "eta_s": 95})
        assert page.progress_bar.value() == 30
        assert len(page.chart._series["loss"]) == 1
        assert "epoch 30/100" in page.lbl_log.text()
        assert "剩余" in page.lbl_log.text()

    def test_emit_marshals_via_invoke_main(self, qapp, monkeypatch):
        from gui.pages.train import page as train_mod

        monkeypatch.setattr(train_mod, "TrainWorker", type("W", (), {}))
        monkeypatch.setattr(train_mod.TrainPage, "_confirm_simulated",
                            lambda self: True)
        page = train_mod.TrainPage()
        captured: list = []

        def _fake_invoke(widget, slot, *args):
            captured.append((widget, slot, args))

        monkeypatch.setattr("gui.core.thread_bridge.invoke_main", _fake_invoke)
        page._emit_epoch_progress({"epoch": 5, "total": 100})
        assert captured and captured[0][1] == "_on_epoch_progress_ui"
        assert captured[0][2][0]["epoch"] == 5

    def test_make_trainer_installs_hook(self, qapp, monkeypatch, tmp_path):
        """真路径 _make_trainer 装引擎进度钩子并持引用。"""
        from gui.pages.train import page as train_mod

        class _Eng(SegYoloEngine):
            installed = None

            def set_progress_callback(self, cb):
                _Eng.installed = cb

        monkeypatch.setattr(
            "models.supervised.registry.get_default_registry",
            lambda: type("R", (), {
                "has": lambda self, t: True,
                "get": lambda self, t: _Eng(),
            })(),
        )
        monkeypatch.setattr(train_mod, "TrainWorker", type("W", (), {}))
        monkeypatch.setattr(train_mod.TrainPage, "_confirm_simulated",
                            lambda self: True)
        page = train_mod.TrainPage()
        trainer = page._make_trainer(_cfg(tmp_path))
        assert trainer is not None
        assert _Eng.installed == page._emit_epoch_progress  # 绑定方法按 ==
        assert page._active_engine is not None
