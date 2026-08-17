"""主线程重活迁移测试（W3-T3，架构审查 P1-3）。

data_manage 导入/划分、label AI 预标注、predict 单张推理必须移出 UI 线程：
FakeThread 替身记录线程创建并同步执行 worker（模拟完整跑完），证明
① 重活经 threading.Thread 分发（旧内联实现创建 0 线程 → RED）
② 完成后经 invoke_main 队列事件回主线程刷新（按钮恢复/结果落地）。
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

# 1x1 真实 PNG（缩略图加载器/QPixmap 可解码，避免空字节图引发告警）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    """threading.Thread 替身：记录创建并同步执行 target。"""

    created = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        FakeThread.created.append(self)

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        return None


@pytest.fixture
def fake_threads(monkeypatch):
    FakeThread.created = []
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


# ============================== data_manage ============================== #
@pytest.mark.unit
def test_import_images_runs_in_worker(qapp, fake_threads, tmp_path, monkeypatch):
    from gui.pages.data_manage.page import DataManagePage

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()
    for i in range(3):
        (src / f"img{i}.png").write_bytes(PNG_1PX)

    monkeypatch.setattr(
        "gui.pages.data_manage.page.pick_directory", lambda *a, **k: str(src)
    )
    page = DataManagePage()
    page._image_dir = str(dst)

    page._import_images()

    assert len(fake_threads.created) == 1, "导入必须在 worker 线程执行"
    qapp.processEvents()  # 投递 invoke_main 队列事件 → 完成槽
    assert page.btn_import.isEnabled()
    assert len(list(dst.glob("*.png"))) == 3


@pytest.mark.unit
def test_split_dataset_runs_in_worker(qapp, fake_threads, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from gui.pages.data_manage.page import DataManagePage

    base = tmp_path / "data"
    base.mkdir()
    for i in range(10):
        (base / f"i{i}.png").write_bytes(PNG_1PX)

    monkeypatch.setattr(
        "gui.pages.data_manage.page.pick_directory", lambda *a, **k: str(base)
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    page = DataManagePage()
    page._image_dir = str(base)

    page._split_dataset()

    assert len(fake_threads.created) == 1, "划分必须在 worker 线程执行"
    qapp.processEvents()
    assert page.btn_split.isEnabled()
    for sub in ("train", "val", "test"):
        assert (base / sub).is_dir()
    total = sum(
        len(list((base / s).glob("*.png"))) for s in ("train", "val", "test")
    )
    assert total == 10


# ============================== label 预标注 ============================== #
@pytest.mark.unit
def test_ai_prelabel_runs_in_worker(qapp, fake_threads, monkeypatch):
    from labeling.base import AnnotationMode, Shape
    from gui.pages.label import page as label_page_mod

    page = label_page_mod.LabelPage()
    page._image_path = "demo.png"

    def _fake_run(image_path):
        assert image_path == "demo.png"
        return [
            Shape(
                AnnotationMode.RECTANGLE,
                ((1.0, 2.0), (30.0, 40.0)),
                label="defect",
            )
        ]

    monkeypatch.setattr(label_page_mod, "run_ai_prelabel", _fake_run)

    page._ai_prelabel()

    assert len(fake_threads.created) == 1, "预标注必须在 worker 线程执行"
    qapp.processEvents()
    assert page.btn_ai_prelabel.isEnabled()
    assert len(page.canvas.shapes) == 1
    assert page.canvas.shapes[0].mode is AnnotationMode.RECTANGLE


# ============================== thread_bridge 回归 ============================== #
@pytest.mark.unit
def test_invoke_main_delivers_all_primitive_types(qapp):
    """W3-T3 修复回归：str 载荷旧版必崩（QString eval 链），现全类型可靠送达。"""
    from PySide6.QtCore import QObject, Slot

    from gui.core.thread_bridge import invoke_main

    class _Sink(QObject):
        got = []

        @Slot(int)
        def ri(self, v):
            _Sink.got.append(("int", v))

        @Slot(str)
        def rs(self, v):
            _Sink.got.append(("str", v))

        @Slot(float)
        def rf(self, v):
            _Sink.got.append(("float", v))

        @Slot(bool)
        def rb(self, v):
            _Sink.got.append(("bool", v))

        @Slot(dict)
        def rd(self, v):
            _Sink.got.append(("dict", v))

        @Slot(list)
        def rl(self, v):
            _Sink.got.append(("list", v))

    sink = _Sink()
    _Sink.got = []
    invoke_main(sink, "ri", 7)
    invoke_main(sink, "rs", "文本")
    invoke_main(sink, "rf", 0.25)
    invoke_main(sink, "rb", True)
    invoke_main(sink, "rd", {"onnx": "a.onnx"})
    invoke_main(sink, "rl", [("mAP", "0.9", "平均值")])
    qapp.processEvents()

    assert dict(_Sink.got) == {
        "int": 7,
        "str": "文本",
        "float": 0.25,
        "bool": True,
        "dict": {"onnx": "a.onnx"},
        "list": [("mAP", "0.9", "平均值")],
    }

# ==================== W14-C2 追加（P2-15）：deploy 导出线程参数化 ==================== #
@pytest.mark.unit
def test_deploy_export_thread_receives_task_value(qapp, monkeypatch, tmp_path):
    """P2-15 RED：task_value 必须主线程预读（同 fmt/precision :138-140），
    经 Thread 参数传入导出 worker——QComboBox 跨线程只读违 Qt 契约，
    当前 _work() 无参闭包在线程体内自读 currentIndex → RED。"""
    import inspect

    from gui.pages.deploy.page import DeployPage

    class _RecordingThread:
        """只记录创建形态、不执行 worker（本用例聚焦线程创建契约）。"""

        created = []

        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._t, self._a, self._k = target, args, kwargs or {}
            _RecordingThread.created.append(self)

        def start(self):
            pass

    _RecordingThread.created = []
    monkeypatch.setattr(threading, "Thread", _RecordingThread)

    page = DeployPage()
    page._model_edit.setText(str(tmp_path / "m.pt"))
    page._out_edit.setText(str(tmp_path / "out"))
    page._task_combo.setCurrentIndex(3)  # abdet

    page._do_export()

    assert len(_RecordingThread.created) == 1, "导出必须分发到 worker 线程"
    t = _RecordingThread.created[0]
    sig = inspect.signature(t._t)
    assert "task_value" in sig.parameters, (
        "导出线程 target 应接收 task_value 参数（主线程预读后传入），"
        "而非在线程体内读取 QComboBox"
    )
    bound = sig.bind(*t._a, **t._k)
    assert bound.arguments["task_value"] == "abdet", (
        "task_value 应为线程启动前主线程预读的下拉框映射值"
    )


# ============================== predict 单张推理 ============================== #
@pytest.mark.unit
def test_single_infer_runs_in_worker(qapp, fake_threads, monkeypatch):
    from core.interfaces_supervised import DetectionResult, TaskType
    from gui.pages.predict import page as pred_mod

    class _FakeEngine:
        def infer(self, img, threshold=0.5, labels=None):
            return DetectionResult(task=TaskType.DET, score=0.9)

    page = pred_mod.PredictPage()
    page._engine = _FakeEngine()

    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: "fake.png")
    monkeypatch.setattr(
        "core.image_io.imread_unicode",
        lambda p, flags=None: np.zeros((4, 4, 3), np.uint8),
    )

    page._single_infer()

    assert len(fake_threads.created) == 1, "单张推理必须在 worker 线程执行"
    qapp.processEvents()
    assert page.btn_single.isEnabled()
    assert page.table.rowCount() == 1
