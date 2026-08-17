"""deploy 页（gui/pages/deploy）行为测试（W8-T3：48% → 洼地填平）。

覆盖 _do_export 全分支（参数校验 / torch.load 装载与 dict 解包 / 无法识别
格式 / onnx 导出 / TRT 失败降级 / 异常路径）、完成与失败槽、审计日志、
进度槽与 retranslate。导出器与 torch.load 注入，不依赖真权重/TRT。
"""
from __future__ import annotations

import os
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t:
            self._t(*self._a, **self._k)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


class _Model:
    """极简可 eval() 模型对象（torch.load 返回值替身）。"""

    def eval(self):
        pass


class FakeExporter:
    calls = []
    fail_trt = False

    def __init__(self):
        pass

    def export_onnx(self, engine, path, precision=None):
        FakeExporter.calls.append(("onnx", engine.task.value, path, precision))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"onnx-bytes")

    def export_tensorrt(self, onnx_path, trt_path, precision=None):
        FakeExporter.calls.append(("trt", onnx_path, trt_path, precision))
        if FakeExporter.fail_trt:
            raise RuntimeError("TRT not installed")


@pytest.fixture
def fake_exporter(monkeypatch):
    import exporter.supervised_exporter as exp_mod

    FakeExporter.calls = []
    FakeExporter.fail_trt = False
    monkeypatch.setattr(exp_mod, "SupervisedExporter", FakeExporter)
    return FakeExporter


@pytest.fixture
def deploy_page(qapp, tmp_path, monkeypatch):
    from gui.pages.deploy.page import DeployPage

    page = DeployPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    page._model_edit.setText(str(tmp_path / "best.pt"))
    page._out_edit.setText(str(tmp_path / "out"))
    return page


def _fake_torch_load(monkeypatch, payload):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch, "load", lambda path, **k: payload)


# ============================== 参数校验 ============================== #
@pytest.mark.unit
def test_do_export_requires_paths(deploy_page):
    deploy_page._model_edit.clear()
    deploy_page._do_export()
    assert any("请填写" in t for t, _ in deploy_page._msgs)

    deploy_page._out_edit.clear()
    deploy_page._do_export()
    assert len([m for m in deploy_page._msgs if "请填写" in m[0]]) == 2


@pytest.mark.unit
def test_pick_model_and_outdir(deploy_page, monkeypatch, tmp_path):
    from gui.pages.deploy import page as dep_mod

    monkeypatch.setattr(dep_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "m.pt"))
    monkeypatch.setattr(dep_mod, "pick_directory",
                        lambda *a, **k: str(tmp_path / "out"))
    deploy_page._pick_model()
    deploy_page._pick_outdir()
    assert deploy_page._model_edit.text().endswith("m.pt")
    assert deploy_page._out_edit.text().endswith("out")


# ============================== 导出成功 ============================== #
@pytest.mark.unit
def test_export_success_onnx_and_trt(
    deploy_page, fake_threads, fake_exporter, monkeypatch, tmp_path, qapp
):
    _fake_torch_load(monkeypatch, {"model": _Model()})  # dict 含 "model" → 解包

    audit = []
    monkeypatch.setattr(
        "core.audit_logger.log_model_export",
        lambda **kw: audit.append(kw),
    )

    deploy_page._format_combo.setCurrentIndex(2)  # ONNX + TensorRT
    deploy_page._task_combo.setCurrentIndex(0)    # det
    deploy_page._do_export()
    qapp.processEvents()

    kinds = [c[0] for c in fake_exporter.calls]
    assert kinds == ["onnx", "trt"]
    onnx_call = fake_exporter.calls[0]
    assert onnx_call[1] == "det"
    assert onnx_call[2].endswith("det.onnx")
    assert onnx_call[3] == "fp32"
    assert os.path.exists(onnx_call[2])

    assert deploy_page._export_btn.isEnabled() is True
    assert deploy_page._msgs[-1][0] == "导出完成"
    assert "det.onnx" in deploy_page._msgs[-1][1]
    assert "det.engine" in deploy_page._msgs[-1][1]
    assert deploy_page._progress.value() == 100

    # R4-6 审计：task/format/路径落账
    assert audit and audit[0]["task"] == "det"
    assert "onnx" in audit[0]["format"] and "trt" in audit[0]["format"]


@pytest.mark.unit
def test_export_onnx_only_skips_trt(
    deploy_page, fake_threads, fake_exporter, monkeypatch, qapp
):
    _fake_torch_load(monkeypatch, _Model())  # 非字典 → 直接用
    deploy_page._format_combo.setCurrentIndex(0)  # 仅 ONNX
    deploy_page._do_export()
    qapp.processEvents()
    assert [c[0] for c in fake_exporter.calls] == ["onnx"]
    assert deploy_page._msgs[-1][0] == "导出完成"
    assert "det.onnx" in deploy_page._msgs[-1][1]


# ============================== 降级与失败 ============================== #
@pytest.mark.unit
def test_export_trt_failure_degrades_to_onnx(
    deploy_page, fake_threads, fake_exporter, monkeypatch, qapp
):
    _fake_torch_load(monkeypatch, _Model())
    fake_exporter.fail_trt = True
    deploy_page._format_combo.setCurrentIndex(2)
    deploy_page._do_export()
    qapp.processEvents()
    # TRT 失败不中断导出：完成状态、只有 onnx 产物
    assert deploy_page._msgs[-1][0] == "导出完成"
    assert "det.onnx" in deploy_page._msgs[-1][1]
    assert "det.engine" not in deploy_page._msgs[-1][1]


@pytest.mark.unit
def test_export_unrecognized_model_format(
    deploy_page, fake_threads, fake_exporter, monkeypatch, qapp
):
    _fake_torch_load(monkeypatch, 42)  # int 无 eval 属性
    deploy_page._do_export()
    qapp.processEvents()
    assert deploy_page._msgs[-1][0] == "导出失败"
    assert "无法识别" in deploy_page._msgs[-1][1]
    assert deploy_page._progress.value() == 0
    assert deploy_page._export_btn.isEnabled() is True


@pytest.mark.unit
def test_export_load_exception_reports(
    deploy_page, fake_threads, fake_exporter, monkeypatch, qapp
):
    torch = pytest.importorskip("torch")

    def _boom(path, **k):
        raise RuntimeError("权重损坏")

    monkeypatch.setattr(torch, "load", _boom)
    deploy_page._do_export()
    qapp.processEvents()
    assert deploy_page._msgs[-1][0] == "导出失败"
    assert "权重损坏" in deploy_page._msgs[-1][1]


# ============================== 槽与杂项 ============================== #
@pytest.mark.unit
def test_set_progress_via_invoke_main(deploy_page, qapp):
    deploy_page._set_progress_slot(55)
    qapp.processEvents()
    assert deploy_page._progress.value() == 55
    deploy_page.set_progress(70)  # 直调槽
    assert deploy_page._progress.value() == 70


@pytest.mark.unit
def test_retranslate_refresh_texts(deploy_page):
    deploy_page.retranslate()
    assert deploy_page._title.text() == "模型发布"
    assert deploy_page._export_btn.text() == "导出"
    assert "(seg)" in deploy_page._task_combo.itemText(2)


# ==================== W11-P1 追加：审计失败不静默 ==================== #
@pytest.mark.unit
def test_export_finished_audit_failure_warns_not_silent(
    deploy_page, fake_threads, fake_exporter, monkeypatch, qapp, caplog
):
    """W11-P1：导出完成回调中审计写入失败不得静默吞。

    RED：_on_export_finished 此前 ``except (OSError, ImportError): pass``，
    审计失败零痕迹；应记录 warning（含异常信息）且回调不崩。
    """
    import logging as logging_mod

    _fake_torch_load(monkeypatch, _Model())

    def _audit_boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr("core.audit_logger.log_model_export", _audit_boom)

    with caplog.at_level(logging_mod.WARNING, logger="gui.pages.deploy.page"):
        deploy_page._do_export()
        qapp.processEvents()

    # 完成回调不崩：完成状态照常发出、按钮恢复可用
    assert deploy_page._msgs[-1][0] == "导出完成"
    assert deploy_page._export_btn.isEnabled() is True
    # 审计失败必须留下 warning 痕迹
    warns = [
        r for r in caplog.records
        if r.levelno == logging_mod.WARNING and "审计" in r.getMessage()
    ]
    assert warns, "审计写入失败被静默吞掉：应记录 warning"
    assert any("disk full" in r.getMessage() for r in warns)


# ==================== W13-C3 追加：审计用户归属 ==================== #
@pytest.fixture
def _session_user_cleanup():
    from core.session import reset_current_user

    yield
    reset_current_user()


@pytest.mark.unit
def test_export_audit_records_logged_in_user(
    deploy_page, fake_threads, fake_exporter, monkeypatch, qapp,
    _session_user_cleanup,
):
    """W13-C3：登录后导出审计应记 user=登录名。

    RED：_on_export_finished 此前调 log_model_export 不传 user，
    审计记录恒为默认 "system"，无法归属到登录用户。
    """
    from core.session import set_current_user

    set_current_user("engineer")
    audit = []
    monkeypatch.setattr(
        "core.audit_logger.log_model_export", lambda **kw: audit.append(kw)
    )

    _fake_torch_load(monkeypatch, _Model())
    deploy_page._do_export()
    qapp.processEvents()

    assert audit, "导出完成应记审计"
    assert audit[0].get("user") == "engineer", (
        "导出审计应归属当前登录用户，而非默认 system"
    )
