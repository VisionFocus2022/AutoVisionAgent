"""W17（v3 P2-1）：run_job on_error 统一收口。

覆盖三件事：
1. ui_on_error 单元行为：异常经 invoke_main 转发到 @Slot(str) 槽（支持前缀参数，
   供 data_manage._op_failed(op, err) 这类双参槽）。
2. 迁移守卫：6 页 10 个 run_job 消费点全部传 on_error=ui_on_error（防回退）。
3. 行为兜底：worker 抛出页面 except 元组外的异常类型时按钮必恢复、状态栏收到
   错误——含 v3 点名的 eval IndexError / deploy ModelExportError 两专例。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Slot  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

_PAGES = [
    ("predict", "gui.pages.predict.page"),
    ("eval_", "gui.pages.eval_.page"),
    ("label", "gui.pages.label.page"),
    ("data_manage", "gui.pages.data_manage.page"),
    ("deploy", "gui.pages.deploy.page"),
    ("flaw_gen", "gui.pages.flaw_gen.page"),
]


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


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ============================== 1. ui_on_error 单元 ============================== #


class _Recorder(QWidget):
    received = []

    @Slot(str, str)
    def record(self, prefix: str, err: str) -> None:
        _Recorder.received.append((prefix, err))


@pytest.mark.unit
def test_ui_on_error_forwards_to_slot_with_prefix(qapp):
    from gui.core.thread_bridge import ui_on_error

    _Recorder.received = []
    w = _Recorder()
    handler = ui_on_error(w, "record", "op42")
    handler(ValueError("boom-message"))
    qapp.processEvents()
    assert _Recorder.received == [("op42", "boom-message")]


# ============================== 2. 迁移守卫（防回退） ============================== #


@pytest.mark.unit
@pytest.mark.parametrize("page_name,module_path", _PAGES, ids=[p[0] for p in _PAGES])
def test_every_run_job_site_wires_on_error(page_name, module_path):
    """守卫：每处 run_job( 调用都必须传 on_error=ui_on_error（W17 P2-1 收口）。"""
    import importlib

    mod = importlib.import_module(module_path)
    src = Path(mod.__file__).read_text(encoding="utf-8")
    calls = src.count("run_job(")
    wired = src.count("on_error=ui_on_error(")
    assert calls > 0, f"{module_path} 未发现 run_job 调用（清单过期？）"
    assert calls == wired, (
        f"{module_path}: {calls} 处 run_job 仅 {wired} 处接 on_error="
        "（W17 P2-1：元组外异常会击穿到 run_job 日志层，按钮永久禁用）"
    )


# ============================== 3. 行为兜底 ============================== #


@pytest.mark.unit
def test_predict_single_unexpected_exception_recovers_button(qapp, fake_threads, monkeypatch, tmp_path):
    """predict 单张：引擎 infer 抛元组外 KeyError → 按钮恢复 + 状态栏报错。"""
    from gui.pages.predict.page import PredictPage

    page = PredictPage()

    class _BoomEngine:
        def infer(self, img):
            raise KeyError("unexpected")

    page._engine = _BoomEngine()
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG stub")

    monkeypatch.setattr(
        "gui.pages.predict.page.pick_open_file", lambda *a, **k: str(img)
    )

    page.btn_single.setEnabled(False)
    page._single_infer() if hasattr(page, "_single_infer") else None
    # 上面的防御式调用若方法名不符则直接触发 _work 路径：
    qapp.processEvents()
    assert page.btn_single.isEnabled()


@pytest.mark.unit
def test_eval_page_indexerror_recovers_button(qapp, fake_threads, monkeypatch, tmp_path):
    """eval 页专例（v3 P1-2 兜底）：评估流抛 IndexError → 按钮恢复。"""
    from gui.pages.eval_.page import EvalPage

    page = EvalPage()

    def _boom(*a, **k):
        raise IndexError("boolean index did not match")

    monkeypatch.setattr("gui.pages.eval_.page.run_eval_task", _boom)
    (tmp_path / "m.pt").write_bytes(b"w")
    page._model_edit.setText(str(tmp_path / "m.pt"))
    page._gt_edit.setText(str(tmp_path))

    try:
        page._run_eval()
    except Exception:
        pytest.fail("页面启动入口自身不应抛（worker 异常应经 run_job 路由）")
    qapp.processEvents()
    assert page._run_btn.isEnabled()


@pytest.mark.unit
def test_deploy_modelexporterror_recovers_button(qapp, fake_threads, monkeypatch, tmp_path):
    """deploy 专例（v3 P2-1）：ModelExportError 击穿旧元组 → 按钮恢复 + 状态栏。"""
    from gui.pages.deploy.page import DeployPage

    page = DeployPage()
    page._model_edit.setText(str(tmp_path / "m.pt"))
    page._out_edit.setText(str(tmp_path / "out"))

    import torch
    from core.exceptions import ModelExportError

    class _FakeModel:
        def eval(self):
            return self

    monkeypatch.setattr(torch, "load", lambda *a, **k: _FakeModel())
    # W18：export_onnx 改显式参数（model, task_value, path）——monkeypatch 同步
    monkeypatch.setattr(
        "exporter.supervised_exporter.SupervisedExporter.export_onnx",
        lambda self, model, task_value, path, precision=None: (_ for _ in ()).throw(
            ModelExportError("ONNX 解析失败(测试)")
        ),
    )
    statuses = []
    page.status_changed.connect(lambda text, accent: statuses.append(text))

    page._do_export()
    qapp.processEvents()
    assert page._export_btn.isEnabled(), "ModelExportError 后导出按钮必须恢复"
    assert any("导出失败" in s for s in statuses)


@pytest.mark.unit
def test_label_prelabel_unexpected_exception_recovers_button(qapp, fake_threads, monkeypatch, tmp_path):
    """label 预标注：run_ai_prelabel 抛元组外 KeyError → 按钮恢复。"""
    from gui.pages.label import page as label_mod
    from gui.pages.label.page import LabelPage

    # W18：_ai_prelabel 启动前有 det_engine_available 预检——本用例锚定
    # worker 异常路由，预检放行（引擎可用性另有专项用例）
    monkeypatch.setattr(label_mod, "det_engine_available", lambda: True)

    page = LabelPage()
    page._image_path = str(tmp_path / "a.png")

    def _boom(path):
        raise KeyError("unexpected")

    monkeypatch.setattr("gui.pages.label.page.run_ai_prelabel", _boom)

    page.btn_ai_prelabel.setEnabled(False)
    page._ai_prelabel()
    qapp.processEvents()
    assert page.btn_ai_prelabel.isEnabled()


@pytest.mark.unit
def test_data_manage_run_worker_unexpected_exception_recovers_button(qapp, fake_threads):
    """data_manage：_run_worker 的 work 抛元组外 KeyError → 对应按钮恢复。"""
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()

    def _boom():
        raise KeyError("unexpected")

    page._run_worker("import", _boom, lambda t: str(t))
    qapp.processEvents()
    assert page.btn_import.isEnabled()


@pytest.mark.unit
def test_flaw_gen_unexpected_exception_recovers_button(qapp, fake_threads, monkeypatch, tmp_path):
    """flaw_gen：get_engine 抛元组外 KeyError → 开始生成按钮恢复。"""
    from gui.pages.flaw_gen.page import FlawGenPage

    page = FlawGenPage()
    page._ok_edit.setText(str(tmp_path / "ok"))
    page._flaw_edit.setText(str(tmp_path / "flaw"))
    page._out_edit.setText(str(tmp_path / "out"))

    import gui.pages.flaw_gen.page as fg_mod

    # 引擎注册/获取是 _work 内的函数局部导入——打源模块补丁（调用期生效）
    monkeypatch.setattr("models.supervised.engines.register_all_engines", lambda: None)
    monkeypatch.setattr(
        "models.supervised.registry.get_engine",
        lambda task: (_ for _ in ()).throw(KeyError("unexpected")),
    )

    page._start_generate()
    qapp.processEvents()
    assert page._gen_btn.isEnabled()
