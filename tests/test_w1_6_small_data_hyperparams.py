"""W1-6 小数据训练默认超参修复测试（RED→GREEN）。

PRD：docs/prd-w1-6-small-data-hyperparams.md
- AC-1 显式 SGD lr0=0.01 透传 + N≤50 轮数下限 100（大数据不动）
- AC-2 末轮 P/R/mAP50 三级提取（trainer.metrics → val() → 双缺不抛）
- AC-3 完成状态格式化（有指标显示 P/R/mAP50，无指标空串）
"""
from __future__ import annotations

import pytest

import models.supervised.engines.det_yolo  # noqa: F401  引擎注册副作用
from core.interfaces_supervised import TaskType, TrainConfig
from models.supervised.engines.det_yolo import DetYoloEngine  # det 通道


class _FakeTrainer:
    def __init__(self, metrics):
        self.metrics = metrics


class _FakeValBox:
    def __init__(self, mp, mr, map50):
        self.mp, self.mr, self.map50 = mp, mr, map50


class _FakeValResult:
    def __init__(self):
        self.box = _FakeValBox(0.91, 0.42, 0.63)


class _FakeYOLO:
    """记录 train kwargs 的 YOLO 替身（模块级最近一次调用可取）。"""

    last_train_kwargs: dict | None = None
    last_instance: _FakeYOLO | None = None

    def __init__(self, model=None):
        self.trainer = None
        self._val_result = _FakeValResult()
        self.val_called = False
        _FakeYOLO.last_instance = self

    def train(self, **kwargs):
        _FakeYOLO.last_train_kwargs = dict(kwargs)
        self.trainer = _FakeTrainer(getattr(self, "_train_metrics_after", {}))

    def val(self):
        self.val_called = True
        return self._val_result


def _make_yaml(tmp_path, n_train: int, n_val: int = 3) -> str:
    """构造 P0-1 划分布局的 data.yaml + N 个训练标签。"""
    root = tmp_path / "yolo"
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "val").mkdir(parents=True)
    for i in range(n_train):
        (root / "labels" / "train" / f"img{i}.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    for i in range(n_val):
        (root / "labels" / "val" / f"v{i}.txt").write_text("", encoding="utf-8")
    yaml_path = root / "data.yaml"
    yaml_path.write_text(
        f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\n"
        "nc: 1\nnames:\n  0: defect\n", encoding="utf-8")
    return str(yaml_path)


def _cfg(yaml_path: str, epochs: int = 30) -> TrainConfig:
    return TrainConfig(task=TaskType.DET, epochs=epochs, data_yaml=yaml_path,
                       amp=False, device="cpu")


@pytest.fixture()
def fake_yolo(monkeypatch):
    _FakeYOLO.last_train_kwargs = None
    monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)
    return _FakeYOLO


class TestAc1ExplicitHyperparams:
    def test_small_data_boosts_epochs_and_passes_sgd(self, fake_yolo, tmp_path):
        yaml_path = _make_yaml(tmp_path, n_train=12)
        engine = DetYoloEngine()
        engine.train_epoch(1, _cfg(yaml_path, epochs=30))
        kw = fake_yolo.last_train_kwargs
        assert kw["optimizer"] == "SGD", kw
        assert kw["lr0"] == pytest.approx(0.01)
        assert kw["epochs"] == 100, "N=12≤50 应自适应提升到 100 轮"

    def test_large_data_respects_user_epochs(self, fake_yolo, tmp_path):
        yaml_path = _make_yaml(tmp_path, n_train=55)
        engine = DetYoloEngine()
        engine.train_epoch(1, _cfg(yaml_path, epochs=30))
        assert fake_yolo.last_train_kwargs["epochs"] == 30

    def test_user_higher_epochs_not_lowered(self, fake_yolo, tmp_path):
        yaml_path = _make_yaml(tmp_path, n_train=12)
        engine = DetYoloEngine()
        engine.train_epoch(1, _cfg(yaml_path, epochs=200))
        assert fake_yolo.last_train_kwargs["epochs"] == 200

    def test_effective_epochs_reported_in_metrics(self, fake_yolo, tmp_path):
        yaml_path = _make_yaml(tmp_path, n_train=12)
        engine = DetYoloEngine()
        metrics = engine.train_epoch(1, _cfg(yaml_path, epochs=30))
        assert metrics.get("epochs_effective") == 100


class TestAc2ValMetricsExtraction:
    def test_from_trainer_metrics_det_keys(self, monkeypatch, tmp_path):
        yaml_path = _make_yaml(tmp_path, n_train=12)

        class _WithMetrics(_FakeYOLO):
            def __init__(self, model=None):
                super().__init__(model)
                self._train_metrics_after = {
                    "metrics/precision(B)": 0.87, "metrics/recall(B)": 0.53,
                    "metrics/mAP50(B)": 0.64,
                }

        monkeypatch.setattr("ultralytics.YOLO", _WithMetrics)
        engine = DetYoloEngine()
        metrics = engine.train_epoch(1, _cfg(yaml_path))
        assert metrics["precision"] == pytest.approx(0.87)
        assert metrics["recall"] == pytest.approx(0.53)
        assert metrics["map50"] == pytest.approx(0.64)

    def test_fallback_to_val_when_trainer_empty(self, fake_yolo, tmp_path):
        yaml_path = _make_yaml(tmp_path, n_train=12)
        engine = DetYoloEngine()
        metrics = engine.train_epoch(1, _cfg(yaml_path))
        inst = fake_yolo.last_instance
        assert inst.val_called, "trainer.metrics 空时应 fallback val()"
        assert metrics["precision"] == pytest.approx(0.91)
        assert metrics["recall"] == pytest.approx(0.42)
        assert metrics["map50"] == pytest.approx(0.63)

    def test_graceful_when_both_absent(self, fake_yolo, tmp_path):
        yaml_path = _make_yaml(tmp_path, n_train=12)

        class _Broken(_FakeYOLO):
            def val(self):
                raise RuntimeError("no val")

        import ultralytics as ul
        ul.YOLO = _Broken
        try:
            engine = DetYoloEngine()
            metrics = engine.train_epoch(1, _cfg(yaml_path))
            assert "precision" not in metrics
            assert "map50" not in metrics
            assert "loss" in metrics, "缺指标时基础 metrics 不应丢"
        finally:
            ul.YOLO = _FakeYOLO


class TestAc3StatusFormatting:
    def test_format_with_full_metrics(self):
        from gui.pages.train.page import _format_final_metrics
        s = _format_final_metrics({"precision": 0.87, "recall": 0.53,
                                   "map50": 0.642})
        assert "P=0.87" in s and "R=0.53" in s and "mAP50=0.64" in s

    def test_format_empty_metrics_returns_empty(self):
        from gui.pages.train.page import _format_final_metrics
        assert _format_final_metrics({}) == ""
        assert _format_final_metrics(None) == ""

    def test_format_partial_metrics_returns_empty(self):
        from gui.pages.train.page import _format_final_metrics
        assert _format_final_metrics({"precision": 0.5}) == ""
