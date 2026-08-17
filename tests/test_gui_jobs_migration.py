"""W15-J3：P2-1 迁移批次 B（label/predict/deploy → run_job）行为契约。

覆盖四组 RED（动手前须先跑出失败记录）：
1. 迁移守卫：三页源码无裸 threading.Thread 直调、必须消费 run_job（P2-1）；
2. deploy 导出经 run_job 分发 + task_value 主线程预读形态保持（W14-C2），
   worker 体内触碰 QComboBox.currentIndex 立即炸；
3. P2-19 关键操作日志：label 保存标注/AI 预标注开始、predict 批量开始/
   完成/导出、deploy 导出开始/完成（caplog 断言）；
4. P2-2 原子写：predict 批量 batch_results.json 经 temp+os.replace 落盘
   （机制断言：replace 被调用且源为 .tmp 临时文件）+ 故障注入
   （replace 抛 OSError → 既有文件内容完好未截断）。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402

# 1x1 真实 PNG（可解码；批量列表只需文件存在）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    """threading.Thread 替身：记录创建并同步执行 target（沿用全仓接缝）。"""

    created = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}
        FakeThread.created.append(self)

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def fake_threads(monkeypatch):
    FakeThread.created = []
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


class _FakeMsgBox:
    """QMessageBox 替身：记录统计文本，exec() 不阻塞。"""

    last_text = ""

    def __init__(self, parent=None):
        pass

    def setIcon(self, _i):
        pass

    def setWindowTitle(self, _t):
        pass

    def setText(self, text):
        _FakeMsgBox.last_text = text

    def exec(self):
        return 0


def _det_result(n_boxes=1, score=0.9):
    boxes = np.array([[1, 1, 20, 20], [5, 5, 30, 30]][:n_boxes], dtype=float)
    return DetectionResult(
        task=TaskType.DET, score=score, scores=(score,) * n_boxes,
        labels=("crack", "hole")[:n_boxes], boxes=boxes,
    )


# ============================== 1. 迁移守卫（P2-1） ============================== #
@pytest.mark.unit
def test_three_pages_no_bare_threading_thread():
    """P2-1 迁移守卫：label×3/predict×2/deploy×1 裸线程全部改经 run_job。"""
    from gui.pages.label import page as label_mod
    from gui.pages.predict import page as pred_mod
    from gui.pages.deploy import page as dep_mod

    for mod in (label_mod, pred_mod, dep_mod):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "threading.Thread" not in src, (
            f"{mod.__name__} 仍存在裸 threading.Thread 直调（P2-1 迁移未完成）"
        )
        assert "run_job(" in src, f"{mod.__name__} 未消费 gui.core.jobs.run_job"


# ============================== 2. deploy run_job 契约 ============================== #
@pytest.mark.unit
def test_deploy_export_dispatched_via_run_job(qapp, monkeypatch, tmp_path):
    """W14-C2（P2-15）→ W15-J3：task_value 主线程预读形态在 run_job 迁移后保持。

    ① 导出经 run_job 分发（恰好一次、任务名固定）；
    ② 预读的 task_value 真实流入 exporter（"abdet"）；
    ③ worker 执行期间毒化 combo——任何跨线程 currentIndex 触碰立即炸。
    """
    torch = pytest.importorskip("torch")
    from gui.pages.deploy import page as dep_mod

    class _Model:
        def eval(self):
            pass

    monkeypatch.setattr(torch, "load", lambda path, **k: _Model())

    exporter_calls = []

    class _Exporter:
        def __init__(self):
            pass

        def export_onnx(self, engine, path, precision=None):
            exporter_calls.append(("onnx", engine.task.value, path, precision))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"onnx")

        def export_tensorrt(self, onnx_path, trt_path, precision=None):
            exporter_calls.append(("trt", onnx_path, trt_path, precision))

    import exporter.supervised_exporter as exp_mod

    monkeypatch.setattr(exp_mod, "SupervisedExporter", _Exporter)

    def _poison_combo():
        raise AssertionError("worker 不得跨线程读取 QComboBox.currentIndex")

    captured = []

    def fake_run_job(fn, *, name, on_error=None):
        captured.append((fn, name))
        # 主线程预读已发生（run_job 调用点之前）；此后 worker 不得再碰 combo
        page._task_combo.currentIndex = _poison_combo
        fn()
        return None

    monkeypatch.setattr(dep_mod, "run_job", fake_run_job)

    page = dep_mod.DeployPage()
    page._model_edit.setText(str(tmp_path / "m.pt"))
    page._out_edit.setText(str(tmp_path / "out"))
    page._task_combo.setCurrentIndex(3)  # abdet

    page._do_export()

    assert len(captured) == 1, "导出必须经 run_job 分发到 worker（且仅一次）"
    assert captured[0][1] == "deploy_export"
    assert exporter_calls and exporter_calls[0][1] == "abdet", (
        "主线程预读的 task_value 必须原样流入导出器（W14-C2 形态保持）"
    )


# ============================== 3. P2-19 操作日志 ============================== #
@pytest.mark.unit
def test_label_save_logs_operation(qapp, monkeypatch, tmp_path, caplog):
    """P2-19：保存标注落 info（操作+路径+形状数）。"""
    from gui.pages.label import page as label_mod
    from labeling import AnnotationMode

    page = label_mod.LabelPage()
    page.canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, label="crack",
        points=[(1.0, 1.0), (5.0, 5.0)],
    )
    out = tmp_path / "a.json"
    monkeypatch.setattr(label_mod, "pick_save_file", lambda *a, **k: str(out))

    with caplog.at_level(logging.INFO, logger="gui.pages.label.page"):
        page.save()

    logged = [r.getMessage() for r in caplog.records
              if r.levelno == logging.INFO]
    assert any("保存标注" in m and str(out) in m for m in logged), (
        f"保存标注应记 info 日志（含路径），got: {logged}"
    )


@pytest.mark.unit
def test_label_ai_prelabel_logs_start(qapp, fake_threads, monkeypatch, caplog):
    """P2-19：AI 预标注开始落 info（含图像路径）。"""
    from gui.pages.label import page as label_mod

    page = label_mod.LabelPage()
    page._image_path = "demo.png"
    monkeypatch.setattr(label_mod, "run_ai_prelabel", lambda p: [])

    with caplog.at_level(logging.INFO, logger="gui.pages.label.page"):
        page._ai_prelabel()
    qapp.processEvents()

    logged = [r.getMessage() for r in caplog.records
              if r.levelno == logging.INFO]
    assert any("AI 预标注开始" in m and "demo.png" in m for m in logged), (
        f"AI 预标注开始应记 info 日志，got: {logged}"
    )


@pytest.mark.unit
def test_predict_batch_logs_start_and_done(
    qapp, fake_threads, tmp_path, monkeypatch, caplog
):
    """P2-19：批量推理开始（目录+张数）/完成（count/total）落 info。"""
    from gui.pages.predict import page as pred_mod

    d = tmp_path / "batch"
    d.mkdir()
    (d / "a.png").write_bytes(PNG_1PX)

    class _Engine:
        def infer_batch(self, paths):
            return [_det_result(2)]

    page = pred_mod.PredictPage()
    page._engine = _Engine()
    page._project_dir = str(tmp_path)
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    with caplog.at_level(logging.INFO, logger="gui.pages.predict.page"):
        page._batch_infer()
        qapp.processEvents()

    logged = [r.getMessage() for r in caplog.records
              if r.levelno == logging.INFO]
    assert any("批量推理开始" in m for m in logged), f"got: {logged}"
    assert any("批量推理完成" in m for m in logged), f"got: {logged}"


@pytest.mark.unit
def test_predict_exports_logged(qapp, tmp_path, monkeypatch, caplog):
    """P2-19：导出 CSV/JSON 落 info（含目标路径）。"""
    from gui.pages.predict import page as pred_mod

    page = pred_mod.PredictPage()
    page._results = [
        {"file": "a.png", "task": "det", "score": 0.9,
         "boxes": [[1, 2, 3, 4]], "labels": ["crack"]},
    ]

    with caplog.at_level(logging.INFO, logger="gui.pages.predict.page"):
        monkeypatch.setattr(pred_mod, "pick_save_file",
                            lambda *a, **k: str(tmp_path / "r.json"))
        page._export_json()
        monkeypatch.setattr(pred_mod, "pick_save_file",
                            lambda *a, **k: str(tmp_path / "r.csv"))
        page._export_csv()

    logged = [r.getMessage() for r in caplog.records
              if r.levelno == logging.INFO]
    assert any("导出JSON" in m and "r.json" in m for m in logged), (
        f"got: {logged}"
    )
    assert any("导出CSV" in m and "r.csv" in m for m in logged), (
        f"got: {logged}"
    )


class _DeployModel:
    def eval(self):
        pass


@pytest.fixture
def deploy_page_fakes(qapp, monkeypatch, tmp_path):
    torch = pytest.importorskip("torch")
    from gui.pages.deploy import page as dep_mod

    monkeypatch.setattr(torch, "load", lambda path, **k: _DeployModel())

    class _Exporter:
        def __init__(self):
            pass

        def export_onnx(self, engine, path, precision=None):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"onnx")

        def export_tensorrt(self, onnx_path, trt_path, precision=None):
            pass

    import exporter.supervised_exporter as exp_mod

    monkeypatch.setattr(exp_mod, "SupervisedExporter", _Exporter)

    page = dep_mod.DeployPage()
    page._model_edit.setText(str(tmp_path / "m.pt"))
    page._out_edit.setText(str(tmp_path / "out"))
    return page


@pytest.mark.unit
def test_deploy_export_logs_start_and_done(
    deploy_page_fakes, fake_threads, qapp, caplog
):
    """P2-19：模型导出开始（模型/输出/任务/格式）/完成（产物）落 info。"""
    with caplog.at_level(logging.INFO, logger="gui.pages.deploy.page"):
        deploy_page_fakes._do_export()
        qapp.processEvents()

    logged = [r.getMessage() for r in caplog.records
              if r.levelno == logging.INFO]
    assert any("模型导出开始" in m for m in logged), f"got: {logged}"
    assert any("模型导出完成" in m for m in logged), f"got: {logged}"


# ============================== 4. P2-2 原子写 ============================== #
def _batch_page(qapp, tmp_path, monkeypatch):
    from gui.pages.predict import page as pred_mod

    d = tmp_path / "batch"
    d.mkdir()
    (d / "a.png").write_bytes(PNG_1PX)
    (d / "b.png").write_bytes(PNG_1PX)

    class _Engine:
        def infer_batch(self, paths):
            return [_det_result(2) for _ in paths]

    page = pred_mod.PredictPage()
    page._engine = _Engine()
    page._project_dir = str(tmp_path)
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)
    return page


@pytest.mark.unit
def test_batch_results_json_write_is_atomic(
    qapp, fake_threads, tmp_path, monkeypatch
):
    """P2-2 机制断言：batch_results.json 必须 temp 写 + os.replace 原子落盘。

    RED（迁移前）：直写 open(out_path,"w")，os.replace 从不被调用。
    """
    page = _batch_page(qapp, tmp_path, monkeypatch)

    real_replace = os.replace
    replace_calls = []

    def spy_replace(src, dst):
        replace_calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    page._batch_infer()
    qapp.processEvents()

    assert replace_calls, "批量结果必须经 os.replace 原子落盘（P2-2）"
    src, dst = replace_calls[0]
    assert os.path.basename(dst) == "batch_results.json"
    assert src.endswith(".tmp"), f"replace 源必须是临时文件，got: {src}"
    assert os.path.dirname(src) == os.path.dirname(dst), "临时文件须同目录"
    assert not os.path.exists(src), "replace 成功后临时文件应已消费"

    data = json.loads(Path(dst).read_text("utf-8"))
    assert len(data) == 2  # 原子写不得改变内容契约


@pytest.mark.unit
def test_batch_results_original_intact_when_replace_fails(
    qapp, fake_threads, tmp_path, monkeypatch, caplog
):
    """P2-2 故障注入：os.replace 抛 OSError → 既有 batch_results.json 完好。

    RED（迁移前）：直写 open(out_path,"w") 先截断再写——replace 失败与否
    无关，旧内容已被覆盖丢失。
    """
    page = _batch_page(qapp, tmp_path, monkeypatch)

    monkeypatch.setattr(time, "time", lambda: 1_700_000_000)
    results_dir = tmp_path / "results" / "batchPredict_1700000000"
    results_dir.mkdir(parents=True)
    out_file = results_dir / "batch_results.json"
    sentinel = '{"previous_run": true}'
    out_file.write_text(sentinel, encoding="utf-8")

    def boom_replace(src, dst):
        raise OSError("replace failed (disk full)")

    monkeypatch.setattr(os, "replace", boom_replace)

    with caplog.at_level(logging.ERROR, logger="gui.core.jobs"):
        page._batch_infer()  # 不得抛：run_job 路由异常落日志
        qapp.processEvents()

    assert out_file.read_text(encoding="utf-8") == sentinel, (
        "os.replace 失败时既有 batch_results.json 必须完好（"
        "直写会先截断旧文件——P2-2 数据损坏路径）"
    )
    # run_job 兜底路由：worker 异常不得静默
    assert any("后台任务" in r.getMessage() for r in caplog.records), (
        "replace 失败的 worker 异常应经 run_job 落 ERROR 日志"
    )
