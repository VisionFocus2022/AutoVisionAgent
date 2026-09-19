"""VisionModelDispatcher 灰度归一测试（DEF-POLE-SEG-GRAY，2026-09-19）。

工业灰度图（8bit BMP/灰度相机）按 [H,W,1] 契约直传时，ultralytics 3 通道卷积权重
报 "expected input to have 3 channels, but got 1"——serving 公共入口
infer_supervised 统一转 BGR。回归锚：三种输入形态的引擎侧收图形状。
"""
from __future__ import annotations

import numpy as np
import pytest

import industrial_vision_platform.vision_dispatcher as vp
from core.interfaces_supervised import DetectionResult, TaskType


class _RecordingEngine:
    """记录 infer 收到的图像（含形状），供归一断言。"""

    def __init__(self, task: TaskType) -> None:
        self.task = task
        self.received = None

    def load(self, weights_path: str, device: str = "cuda") -> None:  # noqa: ARG002
        pass

    def infer(self, image, threshold: float = 0.5, labels=None) -> DetectionResult:
        self.received = image
        return DetectionResult(task=self.task, score=0.9)

    def unload(self) -> None:
        pass

    release = unload


@pytest.fixture
def dispatcher(monkeypatch):
    d = vp.VisionModelDispatcher(max_loaded=2)
    d._engine_registry_ready = True
    engines: dict = {}
    monkeypatch.setattr(
        vp, "get_engine",
        lambda t: engines.setdefault(t, _RecordingEngine(t)),
    )
    d.load_supervised(TaskType.SEG, "w")
    return d


@pytest.mark.unit
def test_hw1_gray_array_normalized_to_3ch(dispatcher):
    """[H,W,1] 灰度（SHM 契约形态）→ 引擎收到 [H,W,3]。"""
    gray = np.zeros((32, 48, 1), dtype=np.uint8)
    dispatcher.infer_supervised(TaskType.SEG, gray)
    engine = dispatcher._engines[TaskType.SEG]
    assert engine.received.ndim == 3 and engine.received.shape[2] == 3


@pytest.mark.unit
def test_hw_gray_array_normalized_to_3ch(dispatcher):
    """[H,W] 二维灰度 → 引擎收到 [H,W,3]。"""
    gray = np.zeros((32, 48), dtype=np.uint8)
    dispatcher.infer_supervised(TaskType.SEG, gray)
    engine = dispatcher._engines[TaskType.SEG]
    assert engine.received.ndim == 3 and engine.received.shape[2] == 3


@pytest.mark.unit
def test_3ch_passthrough_unchanged(dispatcher):
    """[H,W,3] 彩色图原样直传（不复制、不改动）。"""
    rgb = np.zeros((32, 48, 3), dtype=np.uint8)
    dispatcher.infer_supervised(TaskType.SEG, rgb)
    engine = dispatcher._engines[TaskType.SEG]
    assert engine.received is rgb


@pytest.mark.unit
def test_non_ndarray_passthrough_unchanged(dispatcher):
    """非 ndarray（路径串等）原样直传——归一不拦非数组载荷。"""
    payload = "E:/some/image.bmp"
    dispatcher.infer_supervised(TaskType.SEG, payload)
    engine = dispatcher._engines[TaskType.SEG]
    assert engine.received is payload
