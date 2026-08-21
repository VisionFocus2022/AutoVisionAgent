"""W28（W26 计划 P1）：推理阈值控件——engine.infer 收到 threshold 参数。

背景：引擎接口 infer/infer_batch 均已支持 threshold（默认 0.5），但 GUI
从未传入，也无任何 UI 控件——SKolpha「阈值+对象类型」双参对标的漏项，
全计划性价比最高条目（控件 + 两处传参即达工业工具基线）。
"""
from __future__ import annotations

import base64
import threading

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeThread:
    """threading.Thread 替身：同步执行 target（全仓接缝）。"""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeMsgBox:
    """QMessageBox 替身：批量完成自动弹统计报表，exec() 不阻塞。"""

    def __init__(self, *a, **k):
        pass

    def setIcon(self, *a):
        pass

    def setWindowTitle(self, *a):
        pass

    def setText(self, *a):
        pass

    def exec(self):
        return 0


def _result() -> DetectionResult:
    return DetectionResult(
        task=TaskType.DET, score=0.9,
        boxes=((1.0, 2.0, 30.0, 20.0),), labels=("crack",), scores=(0.9,),
    )


# ============================== 控件在场 ============================== #


@pytest.mark.unit
def test_threshold_spin_exists_and_bounded(qapp):
    """工具栏提供阈值 QDoubleSpinBox：范围 [0.01, 0.99]，默认 0.5。"""
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    spin = getattr(page, "spin_threshold", None)
    assert isinstance(spin, QDoubleSpinBox), "推理页应提供阈值 QDoubleSpinBox"
    assert spin.minimum() == pytest.approx(0.01)
    assert spin.maximum() == pytest.approx(0.99)
    assert spin.value() == pytest.approx(0.5)


# ============================== 单张传参 ============================== #


@pytest.mark.unit
def test_single_infer_passes_threshold(qapp, fake_threads, monkeypatch, tmp_path):
    """单张推理：engine.infer 必须收到 spinbox 当前阈值。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage

    thresholds = []

    class _Engine:
        def infer(self, img, threshold=0.5, labels=None):
            thresholds.append(threshold)
            return _result()

    page = PredictPage()
    page._engine = _Engine()
    img = tmp_path / "a.png"
    img.write_bytes(PNG_1PX)
    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: str(img))

    page.spin_threshold.setValue(0.25)
    page._single_infer()
    qapp.processEvents()

    assert thresholds == [0.25], f"engine.infer 应收到 threshold=0.25, got {thresholds}"


# ============================== 批量传参 ============================== #


@pytest.mark.unit
def test_batch_infer_passes_threshold(qapp, fake_threads, monkeypatch, tmp_path):
    """批量推理：infer_batch 与逐张 infer 回退路径都必须收到阈值。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage

    d = tmp_path / "batch"
    d.mkdir()
    (d / "a.png").write_bytes(PNG_1PX)

    calls = []

    class _Engine:
        def infer_batch(self, paths, threshold=0.5, labels=None):
            calls.append(("batch", threshold))
            return [_result() for _ in paths]

        def infer(self, img, threshold=0.5, labels=None):
            calls.append(("single", threshold))
            return _result()

    page = PredictPage()
    page._engine = _Engine()
    page._project_dir = str(tmp_path)
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    page.spin_threshold.setValue(0.3)
    page._batch_infer()
    qapp.processEvents()

    assert ("batch", 0.3) in calls, f"infer_batch 应收到 threshold=0.3, got {calls}"
