"""W2-3 数据增强参数透传测试（PRD 见 roadmap Wave2 W2-3 行）。

- AC-1 默认全关：model.train kwargs **不含任何增强键**（零回归铁证）
- AC-2 各开关：HSV→hsv_h/s/v；翻转→fliplr=0.5；mosaic→mosaic=1.0
- AC-3 日志留痕：任一开启时适配器记"数据增强预设透传"
- AC-4 页面：三勾选读入 TrainConfig；默认全 False
"""
from __future__ import annotations

import pytest

from core.interfaces_supervised import TaskType, TrainConfig
from models.supervised.engines.seg_yolo import SegYoloEngine

_AUG_KEYS = ("hsv_h", "hsv_s", "hsv_v", "fliplr", "mosaic")


class _FakeYOLO:
    last_kwargs: dict = {}
    callbacks: dict = {}

    def __init__(self, model=None):
        self.trainer = None
        _FakeYOLO.callbacks = {}

    def add_callback(self, event, fn):
        _FakeYOLO.callbacks[event] = fn

    def train(self, **kwargs):
        _FakeYOLO.last_kwargs = kwargs
        self.trainer = None

    def val(self):
        raise RuntimeError("no val")


def _cfg(tmp_path, **aug) -> TrainConfig:
    root = tmp_path / "yolo"
    (root / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (root / "labels" / "train" / "a.txt").write_text(
        "0 0.5 0.5 0.2 0.2 0.3 0.3 0.4 0.4\n"
    )
    y = root / "data.yaml"
    y.write_text("path: x\ntrain: t\nval: v\nnc: 1\nnames: {0: d}\n")
    return TrainConfig(task=TaskType.SEG, epochs=1, small_data_epoch_floor=0,
                       data_yaml=str(y), amp=False, device="cpu", **aug)


@pytest.mark.unit
def test_all_off_passes_no_aug_keys(monkeypatch, tmp_path):
    """AC-1 默认全关：零增强键透传（ultralytics 默认行为零回归）。"""
    monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)
    SegYoloEngine().train_epoch(1, _cfg(tmp_path))
    leaked = [k for k in _FakeYOLO.last_kwargs if k in _AUG_KEYS]
    assert leaked == [], f"全关却透传了增强键: {leaked}"


@pytest.mark.unit
def test_each_toggle_maps_to_preset(monkeypatch, tmp_path):
    """AC-2 三开关各自的预设键值。"""
    monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)

    def _kw_with(**aug):
        SegYoloEngine().train_epoch(1, _cfg(tmp_path, **aug))
        return _FakeYOLO.last_kwargs  # 每次现读（train 会整体替换引用）

    kw = _kw_with(aug_hsv=True)
    assert kw["hsv_h"] == 0.015 and kw["hsv_s"] == 0.7 and kw["hsv_v"] == 0.4
    assert "fliplr" not in kw and "mosaic" not in kw

    kw = _kw_with(aug_flip=True)
    assert kw["fliplr"] == 0.5 and "hsv_h" not in kw

    kw = _kw_with(aug_mosaic=True)
    assert kw["mosaic"] == 1.0

    kw = _kw_with(aug_hsv=True, aug_flip=True, aug_mosaic=True)
    assert all(k in kw for k in _AUG_KEYS)


@pytest.mark.unit
def test_aug_log_trace(monkeypatch, tmp_path, caplog):
    """AC-3 开启时留痕（e2e 开/关对照的日志锚点）；全关无痕。"""
    monkeypatch.setattr("ultralytics.YOLO", _FakeYOLO)
    with caplog.at_level("INFO", logger="models.supervised.engines._yolo_seg_base"):
        SegYoloEngine().train_epoch(1, _cfg(tmp_path, aug_flip=True))
        assert any("数据增强预设透传" in r.message for r in caplog.records)
        caplog.clear()
        SegYoloEngine().train_epoch(1, _cfg(tmp_path))
        assert not any("数据增强预设透传" in r.message
                       for r in caplog.records)


@pytest.mark.unit
def test_page_checkboxes_to_config(qapp, monkeypatch):
    """AC-4 页面开关 → TrainConfig 字段；默认全 False。"""
    from gui.pages.train import page as train_mod

    monkeypatch.setattr(train_mod, "TrainWorker", type("W", (), {}))
    monkeypatch.setattr(train_mod.TrainPage, "_confirm_simulated",
                        lambda self: True)
    page = train_mod.TrainPage()
    cfg = page._build_config()
    assert (cfg.aug_hsv, cfg.aug_flip, cfg.aug_mosaic) == (False, False, False)
    page.chk_aug_hsv.setChecked(True)
    page.chk_aug_mosaic.setChecked(True)
    cfg2 = page._build_config()
    assert (cfg2.aug_hsv, cfg2.aug_flip, cfg2.aug_mosaic) == (True, False, True)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
