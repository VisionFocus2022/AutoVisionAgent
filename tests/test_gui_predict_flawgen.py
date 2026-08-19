"""predict + flaw_gen 页行为测试（W8-T5：46%/55% → 洼地填平）。

predict：模型加载（注册表注入）、单张推理全路径（含审计落账——RED：numpy
boxes 真值 bug 吞审计）、批推理端到端（RED：`if result.boxes` 在 (N,4)
ndarray 上必抛 ValueError → 整批结果丢弃、batch_results.json 恒空）、
CSV/JSON/Excel 导出（含 openpyxl 缺失回退）、legacy 绘制与杂项。
flaw_gen：参数校验、SGAN 生成成功（真图落盘）、空模板目录、引擎诚实失败。
"""
from __future__ import annotations

import json
import os
import sys
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t: self._t(*self._a, **self._k)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


class _FakeMsgBox:
    """QMessageBox 替身：记录统计文本，exec() 不阻塞。"""

    Information = 1
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


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


def _det_result(n_boxes=2, score=0.9):
    boxes = np.array([[1, 1, 20, 20], [5, 5, 30, 30]][:n_boxes], dtype=float)
    return DetectionResult(
        task=TaskType.DET, score=score, scores=(score,) * n_boxes,
        labels=("crack", "hole")[:n_boxes], boxes=boxes,
    )


@pytest.fixture
def pred_page(qapp):
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


# ============================== 模型加载 ============================== #
@pytest.mark.unit
def test_load_model_success_replaces_old_engine(qapp, tmp_path, monkeypatch):
    from gui.pages.predict import page as pred_mod

    monkeypatch.setattr(
        "gui.core.tasks_ui.populate_task_combo",
        lambda combo, only_available=False: combo.addItem("det", TaskType.DET),
    )
    loads, unloads, cleared = [], [], []

    class _Eng:
        def load(self, path, device="cpu"):
            loads.append((path, device))

    class _OldEng:
        def unload(self):
            unloads.append("old")

    class _Reg:
        def __init__(self, has):
            self._has = has

        def has(self, t):
            return self._has

        def get(self, t):
            return _Eng()

        def clear_cache(self, task=None):
            cleared.append(task)

    import models.supervised.registry as reg_mod

    page = pred_mod.PredictPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._engine = _OldEng()  # 旧引擎在位 → 换模须卸载并清缓存
    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _Reg(True))
    monkeypatch.setattr(pred_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "best.pt"))

    page._load_model()
    assert loads and loads[0][0].endswith("best.pt")
    assert unloads == ["old"]
    assert cleared == [TaskType.DET]
    assert page.lbl_model.text() == "best.pt"
    assert any(t == "模型已加载" for t, _ in msgs)

    # 引擎未注册 → 显式失败
    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _Reg(False))
    page._load_model()
    assert any(t == "引擎未注册" for t, _ in msgs)
    assert page.lbl_model.text() == "引擎未注册"


# ============================== 单张推理 ============================== #
@pytest.mark.unit
def test_single_infer_full_path_audits_multibox(
    pred_page, fake_threads, tmp_path, monkeypatch, qapp
):
    """单张推理：预览渲染 + 结果行 + 审计/历史落账。

    RED：_single_done 里 `if result.boxes`（(N,4) numpy）抛 ValueError 被
    `except Exception: pass` 吞掉——真引擎输出下审计永远不落账。
    """
    img = tmp_path / "img.png"
    _png(img)

    class _Engine:
        def infer(self, im):
            return _det_result(n_boxes=2)

    pred_page._engine = _Engine()
    from gui.pages.predict import page as pred_mod

    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: str(img))

    audit, hist = [], []

    class _Hist:
        def add_record(self, **kw):
            hist.append(kw)

    monkeypatch.setattr("core.audit_logger.log_detection_complete",
                        lambda **kw: audit.append(kw))
    monkeypatch.setattr("core.detection_history.get_history", lambda: _Hist())

    pred_page._single_infer()
    qapp.processEvents()

    assert pred_page.table.rowCount() == 1
    assert pred_page.table.item(0, 3).text().startswith("2")  # "2 框"
    assert pred_page.preview.pixmap() is not None
    assert not pred_page.preview.pixmap().isNull()
    assert pred_page.btn_single.isEnabled() is True

    assert audit and audit[0]["result_count"] == 2  # 审计必须落账
    assert hist and hist[0]["image_path"].endswith("img.png")


@pytest.mark.unit
def test_single_infer_read_and_engine_failures(
    pred_page, fake_threads, tmp_path, monkeypatch, qapp
):
    from gui.pages.predict import page as pred_mod

    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not-an-image")
    pred_page._engine = type("E", (), {"infer": lambda self, im: _det_result(1)})()
    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: str(bad))
    pred_page._single_infer()
    qapp.processEvents()
    assert any(t == "推理失败" for t, _ in pred_page._msgs)
    assert pred_page.btn_single.isEnabled() is True

    img = tmp_path / "ok.png"
    _png(img)
    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: str(img))

    def _boom(self, im):
        raise RuntimeError("engine died")

    pred_page._engine = type("E", (), {"infer": _boom})()
    pred_page._single_infer()
    qapp.processEvents()
    assert any(t == "推理失败" and "engine died" in a for t, a in pred_page._msgs)


@pytest.mark.unit
def test_single_infer_requires_engine(pred_page):
    pred_page._single_infer()
    assert any("请先加载模型" in t for t, _ in pred_page._msgs)


# ============================== 批量推理 ============================== #
@pytest.mark.unit
def test_batch_infer_end_to_end(
    pred_page, fake_threads, tmp_path, monkeypatch, qapp
):
    """批推理端到端：结果行 + batch_results.json（numpy 框须可 JSON 序列化）。

    RED：_batch_add_row 里 `if result.boxes` 在 (N,4) ndarray 上抛
    ValueError → 整批被 except 吞 → 表格恒空、json 恒为 []。
    """
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _png(batch_dir / "a.png")
    _png(batch_dir / "b.png")

    def _infer_batch(self, paths):
        return [_det_result(2), _det_result(1)]

    pred_page._engine = type("E", (), {"infer_batch": _infer_batch})()
    pred_page._project_dir = str(tmp_path)
    from gui.pages.predict import page as pred_mod

    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(batch_dir))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    pred_page._batch_infer()
    qapp.processEvents()

    assert pred_page.table.rowCount() == 2
    assert any(t == "批量完成" for t, _ in pred_page._msgs)

    results_dirs = list((tmp_path / "results").glob("batchPredict_*"))
    assert len(results_dirs) == 1
    data = json.loads((results_dirs[0] / "batch_results.json").read_text("utf-8"))
    assert len(data) == 2
    assert data[0]["boxes"] == [[1.0, 1.0, 20.0, 20.0], [5.0, 5.0, 30.0, 30.0]]
    assert data[1]["boxes"] == [[1.0, 1.0, 20.0, 20.0]]

    # 完成后自动弹统计报表（R3-11）
    assert "总图像数: 2" in _FakeMsgBox.last_text


@pytest.mark.unit
def test_batch_infer_requires_engine_and_images(
    pred_page, tmp_path, monkeypatch
):
    pred_page._batch_infer()
    assert any("请先加载模型" in t for t, _ in pred_page._msgs)

    pred_page._engine = type("E", (), {"infer_batch": lambda p: []})()
    from gui.pages.predict import page as pred_mod

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(empty))
    pred_page._batch_infer()
    assert any("目录无图像" in t for t, _ in pred_page._msgs)


# ============================== 导出 ============================== #
@pytest.mark.unit
def test_export_json_writes_results(pred_page, tmp_path, monkeypatch):
    from gui.pages.predict import page as pred_mod

    out = tmp_path / "r.json"
    monkeypatch.setattr(pred_mod, "pick_save_file", lambda *a, **k: str(out))
    pred_page._results = [
        {"file": "a.png", "task": "det", "score": 0.9,
         "boxes": [[1, 2, 3, 4]], "labels": ["crack"]},
    ]
    pred_page._export_json()
    data = json.loads(out.read_text("utf-8"))
    assert data[0]["file"] == "a.png"
    assert any(t == "已导出" for t, _ in pred_page._msgs)


@pytest.mark.unit
def test_export_excel_csv_fallback_when_openpyxl_missing(
    pred_page, tmp_path, monkeypatch
):
    from gui.pages.predict import page as pred_mod

    pred_page._results = [
        {"file": "a.png", "task": "det", "score": 0.9,
         "boxes": [[1, 2, 3, 4]], "labels": ["crack"]},
    ]
    monkeypatch.setitem(sys.modules, "openpyxl", None)  # 强制 ImportError
    monkeypatch.setattr(pred_mod, "pick_save_file",
                        lambda *a, **k: str(tmp_path / "r.xlsx"))
    pred_page._export_excel()
    csv_path = tmp_path / "r.csv"
    assert csv_path.exists()
    assert any("CSV" in t for t, _ in pred_page._msgs)


@pytest.mark.unit
def test_export_excel_real_xlsx(pred_page, tmp_path, monkeypatch):
    from gui.pages.predict import page as pred_mod

    openpyxl = pytest.importorskip("openpyxl", reason="openpyxl 未安装")
    pred_page._results = [
        {"file": "a.png", "task": "det", "score": 0.9,
         "boxes": [[1, 2, 3, 4]], "labels": ["crack"]},
        {"file": "b.png", "task": "det", "score": 0.4,
         "boxes": [], "labels": []},
    ]
    xlsx = tmp_path / "r.xlsx"
    monkeypatch.setattr(pred_mod, "pick_save_file", lambda *a, **k: str(xlsx))
    pred_page._export_excel()
    wb = openpyxl.load_workbook(xlsx)
    assert wb.sheetnames == ["推理结果", "统计"]
    assert wb["推理结果"].max_row == 3  # 表头 + 2 数据行
    assert wb["统计"]["B5"].value == "50.0%"  # 1/2 缺陷率


# ============================== 杂项 ============================== #
@pytest.mark.unit
def test_set_project_dir_draw_legacy_cancel_retranslate(pred_page, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    pred_page.set_project_dir(str(tmp_path))
    assert pred_page._models_dir.endswith("models")

    bare = tmp_path / "bare"
    bare.mkdir()
    pred_page.set_project_dir(str(bare))
    assert pred_page._models_dir is None or pred_page._models_dir.endswith("models")

    # legacy 绘制：numpy 框 + 空框两分支
    pm = QPixmap(60, 40)
    pm.fill(QColor("black"))
    from gui.pages.predict.page import PredictPage as _PP

    assert not _PP._draw_legacy(pm, _det_result(2)).isNull()
    assert not _PP._draw_legacy(QPixmap(10, 10), _det_result(0)).isNull()

    pred_page._batch_cancel_infer()
    assert pred_page._batch_cancel is True
    pred_page.retranslate()
    assert pred_page.btn_batch.text() == "批量推理"


# ============================== flaw_gen 页 ============================== #
@pytest.fixture
def flaw_page(qapp):
    from gui.pages.flaw_gen.page import FlawGenPage

    page = FlawGenPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


@pytest.mark.unit
def test_flaw_validation_three_gates(flaw_page):
    flaw_page._start_generate()
    assert any("OK 模板" in t for t, _ in flaw_page._msgs)

    flaw_page._ok_edit.setText("ok")
    flaw_page._start_generate()
    assert any("缺陷数据库" in t for t, _ in flaw_page._msgs)

    flaw_page._flaw_edit.setText("flaw")
    flaw_page._start_generate()
    assert any("输出目录" in t for t, _ in flaw_page._msgs)


@pytest.mark.unit
def test_flaw_generate_success_writes_synthetic(
    flaw_page, fake_threads, tmp_path, monkeypatch, qapp
):
    from core.interfaces_supervised import TaskType as TT

    ok_dir = tmp_path / "ok"
    flaw_dir = tmp_path / "flaws"
    out_dir = tmp_path / "out"
    ok_dir.mkdir()
    flaw_dir.mkdir()
    _png(ok_dir / "tpl.png")

    loads, infers = [], []

    class _Sgan:
        def load(self, flaw_database, device="cpu"):
            loads.append(flaw_database)

        def infer(self, p):
            infers.append(p)
            return DetectionResult(
                task=TT.SGAN, score=1.0,
                extra={"synthesized_image": np.full((8, 8, 3), 128, np.uint8)},
            )

    import models.supervised.registry as reg_mod

    monkeypatch.setattr(reg_mod, "get_engine", lambda t: _Sgan())

    flaw_page._ok_edit.setText(str(ok_dir))
    flaw_page._flaw_edit.setText(str(flaw_dir))
    flaw_page._out_edit.setText(str(out_dir))
    flaw_page._count_spin.setValue(5)  # min(5, 1 模板) → 1 轮
    flaw_page._start_generate()
    qapp.processEvents()

    assert loads == [str(flaw_dir)]
    assert len(infers) == 1
    syn = out_dir / "synthetic_0000.png"
    assert syn.exists() and syn.stat().st_size > 0
    assert flaw_page._progress.value() == 100
    assert any(t == "缺陷生成完成" and a.startswith("1 ") for t, a in flaw_page._msgs)
    assert flaw_page._gen_btn.isEnabled() is True


@pytest.mark.unit
def test_flaw_empty_ok_dir_fails(flaw_page, fake_threads, tmp_path,
                                 monkeypatch, qapp):
    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()  # 空目录
    import models.supervised.registry as reg_mod

    class _Sgan:
        def load(self, flaw_database, device="cpu"):
            pass

        def infer(self, p):
            raise AssertionError("无模板不应调用 infer")

    monkeypatch.setattr(reg_mod, "get_engine", lambda t: _Sgan())

    flaw_page._ok_edit.setText(str(ok_dir))
    flaw_page._flaw_edit.setText("f")
    flaw_page._out_edit.setText(str(tmp_path / "out"))
    flaw_page._start_generate()
    qapp.processEvents()
    assert any(t == "生成失败" and "OK 模板目录为空" in a
               for t, a in flaw_page._msgs)


@pytest.mark.unit
def test_flaw_engine_error_is_honest(flaw_page, fake_threads, tmp_path,
                                     monkeypatch, qapp):
    """W2 契约：缺缺陷库由引擎诚实 raise，页面不得用占位图冒充。"""
    from core.exceptions import SupervisedEngineError

    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    _png(ok_dir / "tpl.png")
    import models.supervised.registry as reg_mod

    class _Sgan:
        def load(self, flaw_database, device="cpu"):
            raise SupervisedEngineError("缺陷库为空")

    monkeypatch.setattr(reg_mod, "get_engine", lambda t: _Sgan())

    flaw_page._ok_edit.setText(str(ok_dir))
    flaw_page._flaw_edit.setText(str(tmp_path / "noflaw"))
    flaw_page._out_edit.setText(str(tmp_path / "out"))
    flaw_page._start_generate()
    qapp.processEvents()
    assert any(t == "生成失败" and "缺陷库为空" in a
               for t, a in flaw_page._msgs)
    assert not (tmp_path / "out" / "synthetic_0000.png").exists()


# ============================== W21：单张推理预览自适应 ============================== #
@pytest.mark.unit
def test_single_result_preview_fits_viewport(qapp, tmp_path):
    """W21：单张推理预览自适应——竖图不得被固定 scaledToWidth(400) 裁切。

    回归背景：preview 为裸 QLabel（无滚动区），_show_result 曾固定
    scaledToWidth(400)：竖图（800x1800 → 400x900）超出预览区可视高度直接
    裁切（用户观感"结果显示不全"），且 400 定宽浪费可用宽度。期望：按
    当前预览区等比缩放（KeepAspectRatio），页面 resize 后重适配。
    """
    import cv2

    from gui.pages.predict.page import PredictPage

    ok, buf = cv2.imencode(".png", np.zeros((1800, 800, 3), np.uint8))
    assert ok
    img = tmp_path / "tall.png"
    img.write_bytes(buf.tobytes())

    # 真实约束复现：固定尺寸窗口容器（裸 page.resize 会随 pixmap 撑大失真）
    from PySide6.QtWidgets import QMainWindow

    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    win = QMainWindow()
    win.setCentralWidget(page)
    win.setFixedSize(1000, 480)
    win.show()
    qapp.processEvents()
    page._show_result(str(img), DetectionResult(task=TaskType.DET))
    qapp.processEvents()

    pm = page.preview.pixmap()
    assert pm is not None and not pm.isNull(), "预览未设置 pixmap"
    assert pm.height() <= page.preview.height() + 2, (
        f"竖图高度 {pm.height()} 超出预览区 {page.preview.height()}（下缘裁切）"
    )
    assert pm.width() <= page.preview.width() + 2

    # resize 放大预览区后重适配（不留旧小图）
    win.setFixedSize(1200, 700)
    qapp.processEvents()
    pm2 = page.preview.pixmap()
    assert pm2.height() <= page.preview.height() + 2
    assert pm2.height() > pm.height(), "放大窗口后预览图应随之重适配放大"
