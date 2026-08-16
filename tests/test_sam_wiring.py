"""SAM 交互式标注接线测试（W4-T3，架构审查 P2-6）。

此前 SamAdapter 生产零调用方：GUI 切到交互式模式后点击静默无效。
接线契约：
- 依赖缺失 → 状态栏明示（不再静默）
- 已加载适配器 → 切模式后自动预热 embedding 并注入 InteractiveLabeler
- 控制器 attach_interactive 仅在交互式模式生效
"""
from __future__ import annotations

import base64
import os
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from labeling.base import AnnotationMode  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    created = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        FakeThread.created.append(self)

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def fake_threads(monkeypatch):
    FakeThread.created = []
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


class FakeAdapter:
    """已加载的假 SAM 适配器。"""

    loaded = True

    def __init__(self):
        self.image = None

    def set_image(self, image):
        self.image = image


@pytest.mark.unit
def test_interactive_without_sam_lib_reports_status(qapp, monkeypatch):
    """依赖缺失时状态栏明示，而非点击静默无效（P2-6 主诉）。"""
    import builtins

    from gui.pages.label.page import LabelPage

    real_import = builtins.__import__

    def _no_sam(name, *args, **kwargs):
        if name == "segment_anything":
            raise ImportError("No module named 'segment_anything'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_sam)

    page = LabelPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._apply_mode(AnnotationMode.INTERACTIVE)

    assert any("SAM" in t or "SAM" in a for t, a in msgs), (
        f"切到交互式模式未明示 SAM 状态：{msgs}"
    )


@pytest.mark.unit
def test_interactive_injects_loaded_adapter(qapp, fake_threads, tmp_path):
    """适配器已加载：切模式自动预热当前帧并注入 InteractiveLabeler。"""
    from gui.pages.label.page import LabelPage

    img_path = tmp_path / "img.png"
    img_path.write_bytes(PNG_1PX)

    page = LabelPage()
    page._image_path = str(img_path)
    adapter = FakeAdapter()
    page._sam_adapter = adapter

    page._apply_mode(AnnotationMode.INTERACTIVE)
    qapp.processEvents()  # 投递 _sam_attach 队列事件

    labeler = page.controller._labeler
    assert labeler is not None
    assert labeler._adapter is adapter, "适配器未注入 InteractiveLabeler"
    assert labeler._image is not None and labeler._image.ndim == 3
    assert adapter.image is not None  # 预热已喂图（embedding 缓存命中）


@pytest.mark.unit
def test_controller_attach_interactive_only_in_interactive_mode(qapp):
    """attach_interactive：非交互式模式返回 False（不误注入）。"""
    from labeling.canvas import AnnotationCanvas
    from labeling.controller import AnnotationController

    c = AnnotationCanvas()
    ctrl = AnnotationController(c, mode=AnnotationMode.POLYGON, label="d")
    assert ctrl.attach_interactive(FakeAdapter()) is False

    ctrl.set_mode(AnnotationMode.INTERACTIVE)
    assert ctrl.attach_interactive(FakeAdapter(), np.zeros((2, 2, 3), np.uint8))
    assert ctrl._labeler._image is not None
