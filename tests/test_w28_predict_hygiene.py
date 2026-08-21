"""W28（W26 计划 P1）：批量推理落盘卫生。

背景（对标审查两处操作员信任债）：
1. 无项目时批量结果写进被扫描数据集目录本身（污染源数据）——
   回退到 workspace 根（resolve_base_root 单源）。
2. 取消后仍无条件写 batch_results.json（空 JSON/截断产物落盘）——
   取消即跳过写盘（表内结果仍在，可手动导出）。
"""
from __future__ import annotations

import base64
import threading

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

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
    Information = 1  # _show_stats 用类属性枚举（QMessageBox.Information 同位）
    instances = 0  # 审计折入：取消路径断言不弹统计

    def __init__(self, *a, **k):
        _FakeMsgBox.instances += 1

    def setIcon(self, *a):
        pass

    def setWindowTitle(self, *a):
        pass

    def setText(self, *a):
        pass

    def exec(self):
        return 0


# ============================== 1. 无项目回退 ============================== #


@pytest.mark.unit
def test_batch_save_dir_no_project_falls_back_to_workspace(tmp_path, monkeypatch):
    """无项目时回退 workspace 根，绝不写进被扫描数据集目录。"""
    from gui.pages.predict import workers as pred_workers

    scanned = tmp_path / "dataset"
    scanned.mkdir()
    ws_root = tmp_path / "ws_root"
    monkeypatch.setattr(pred_workers, "resolve_base_root", lambda: str(ws_root))

    out = pred_workers.batch_save_dir(None, str(scanned))
    assert out.startswith(str(ws_root)), f"回退应在 workspace 根下, got {out}"
    assert "results" in out.replace("\\", "/")
    assert not out.startswith(str(scanned)), "不得污染被扫描数据集目录"


# ============================== 3. 坏权重恢复（审计折入） ============================== #


@pytest.mark.unit
def test_load_model_supervised_engine_error_recovers(qapp, monkeypatch, tmp_path):
    """坏 checkpoint 抛 SupervisedEngineError → 状态栏诚实报加载失败
    （旧元组漏收则逃出槽函数、引擎残留半加载态）。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage
    from core.exceptions import SupervisedEngineError

    page = PredictPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))

    class _BadReg:
        def has(self, t):
            return True

        def get(self, t):
            class _BadEngine:
                def load(self, path, device="cpu"):
                    raise SupervisedEngineError("权重损坏", task="det")

            return _BadEngine()

    import models.supervised.registry as reg_mod

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _BadReg())
    monkeypatch.setattr(
        pred_mod, "pick_open_file", lambda *a, **k: str(tmp_path / "bad.pt")
    )

    page._load_model()
    qapp.processEvents()

    assert any(t == "模型加载失败" and "权重损坏" in a for t, a in msgs), (
        f"坏权重应诚实报错，got: {msgs}"
    )
    assert page.lbl_model.text() == "加载失败"


# ============================== 2. 取消不落盘 ============================== #


@pytest.mark.unit
def test_batch_cancel_skips_batch_results_json(
    qapp, fake_threads, monkeypatch, tmp_path
):
    """取消后不得写 batch_results.json（现状：写空/截断 JSON 到非空目录）。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage
    from core.interfaces_supervised import DetectionResult, TaskType

    d = tmp_path / "batch"
    d.mkdir()
    # 两张图：第 1 张推理中触发取消，第 2 张的头部检查即刻停机并标记 cancelled
    (d / "a.png").write_bytes(PNG_1PX)
    (d / "b.png").write_bytes(PNG_1PX)

    class _CancelEngine:
        """首图推理中模拟用户点击取消。"""

        def __init__(self, page):
            self._page = page

        def infer(self, img, threshold=0.5, labels=None):
            self._page._batch_cancel_infer()
            return DetectionResult(task=TaskType.DET, score=0.5)

    page = PredictPage()
    page._engine = _CancelEngine(page)
    page._project_dir = str(tmp_path)
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    _FakeMsgBox.instances = 0
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    page._batch_infer()
    qapp.processEvents()

    results_root = tmp_path / "results"
    leftovers = (
        list(results_root.rglob("batch_results.json")) if results_root.exists() else []
    )
    assert leftovers == [], f"取消后不得落盘 batch_results.json: {leftovers}"
    assert page.btn_batch.isEnabled(), "取消路径必须恢复按钮"
    # 审计折入（取消反馈）：状态栏显式告知未落盘；不得弹统计报表
    assert any(t == "批量已取消" and "未落盘" in a for t, a in page._msgs), (
        f"取消后状态栏应含未落盘提示，got: {page._msgs}"
    )
    assert not any(t == "批量完成" for t, _ in page._msgs)
    assert _FakeMsgBox.instances == 0, "取消路径不得弹统计报表"
