"""predict 页尾巴补测（W10-T5：85% → 填平权威覆盖报告剩余缺口）。

针对 gui/pages/predict/page.py：
- _boxes_to_jsonable None / 纯 list（无 tolist）兜底；
- _load_model 取消、旧引擎 unload 抛错被吞、get_config 设备解析
  （cuda 可用保持 / cuda 不可用回退 cpu / torch ImportError 回退 /
  config ImportError 保持 cpu）、引擎 load 失败状态；
- _single_infer 取消、_single_done 空 pending 早退、审计块异常被吞；
- 批量：目录取消、逐张路径（无 infer_batch）+ imread 失败 continue、
  批级取消 break（>16 张跨批次）、infer_batch 异常被吞 + 进度上报；
- _show_result：sv 渲染 RuntimeError 回退旧画法、sv_bridge ImportError
  回退、QPixmap 空图早退；
- 导出 JSON/Excel 空态与取消、真 xlsx 双表内容（openpyxl 3.1.5 已装）、
  _show_stats 空态、retranslate。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import types

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
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


def _png(path, w=16, h=12):
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


@pytest.fixture
def det_page(qapp, monkeypatch):
    """任务下拉固定为 DET 的预测页（_load_model 系列测试用）。"""
    monkeypatch.setattr(
        "gui.core.tasks_ui.populate_task_combo",
        lambda combo, only_available=False: combo.addItem("det", TaskType.DET),
    )
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


def _install_registry(monkeypatch, engine_factory, has=True):
    """注入假注册表，返回 clear_cache 调用记录。"""
    import models.supervised.registry as reg_mod

    cleared = []

    class _Reg:
        def has(self, t):
            return has

        def get(self, t):
            return engine_factory()

        def clear_cache(self, task=None):
            cleared.append(task)

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _Reg())
    return cleared


# ============================== _boxes_to_jsonable ============================== #
@pytest.mark.unit
def test_boxes_to_jsonable_none_and_plain_list_fallback():
    from gui.pages.predict.page import _boxes_to_jsonable

    assert _boxes_to_jsonable(None) is None
    # 纯 list/tuple 输入：无 tolist 属性 → 逐行 list() 兜底
    plain = _boxes_to_jsonable([[1, 2, 3, 4], (5, 6, 7, 8)])
    assert plain == [[1, 2, 3, 4], [5, 6, 7, 8]]
    assert all(isinstance(b, list) for b in plain)
    json.dumps(plain)  # 兜底结果必须 JSON 可序列化
    # ndarray 走 tolist 主路径
    assert _boxes_to_jsonable(np.array([[1.0, 2, 3, 4]])) == [[1.0, 2.0, 3.0, 4.0]]


# ============================== _load_model 尾巴 ============================== #
@pytest.mark.unit
def test_load_model_cancelled_dialog(det_page, monkeypatch):
    from gui.pages.predict import page as pred_mod

    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: "")
    det_page._load_model()
    assert det_page._model_path is None
    assert det_page.lbl_model.text() == "未加载"
    assert det_page._msgs == []  # 取消：无任何状态上报


@pytest.mark.unit
def test_load_model_old_engine_unload_errors_swallowed(
    det_page, tmp_path, monkeypatch
):
    """旧引擎 unload 抛 RuntimeError（引擎已释放）与 AttributeError（无该方法）
    均须被吞——卸载失败不得阻断换新模型。"""
    from gui.pages.predict import page as pred_mod

    loads = []

    class _Eng:
        def load(self, path, device="cpu"):
            loads.append(device)

    class _BadOld:
        def unload(self):
            raise RuntimeError("engine already freed")

    cleared = _install_registry(monkeypatch, _Eng)
    monkeypatch.setattr(pred_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "m.pt"))

    det_page._engine = _BadOld()
    det_page._load_model()  # RuntimeError 被吞
    assert len(loads) == 1
    assert cleared == [TaskType.DET]

    # 此时 _engine 是 _Eng（无 unload 方法）→ AttributeError 被吞
    det_page._load_model()
    assert len(loads) == 2
    assert cleared == [TaskType.DET, TaskType.DET]
    assert det_page.lbl_model.text() == "m.pt"


@pytest.mark.unit
def test_load_model_device_resolution(det_page, tmp_path, monkeypatch):
    """get_config 设备解析四分支：cuda 可用保持 / 不可用回退 /
    torch ImportError 回退 / config ImportError 保持 cpu。"""
    pytest.importorskip("torch")
    from gui.pages.predict import page as pred_mod

    devices = []

    class _Eng:
        def load(self, path, device="cpu"):
            devices.append(device)

    _install_registry(monkeypatch, _Eng)
    monkeypatch.setattr(pred_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "m.pt"))

    def _cfg(device):
        return types.SimpleNamespace(
            inference=types.SimpleNamespace(device=device))

    # ① 配置 cuda + cuda 可用 → 保持 cuda
    monkeypatch.setattr("core.config.get_config", lambda: _cfg("cuda"))
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    det_page._load_model()
    assert devices == ["cuda"]

    # ② 配置 cuda + cuda 不可用 → 回退 cpu
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    det_page._load_model()
    assert devices == ["cuda", "cpu"]

    # ③ 配置 cuda + torch 缺失（ImportError）→ 回退 cpu
    monkeypatch.setitem(sys.modules, "torch", None)
    det_page._load_model()
    assert devices == ["cuda", "cpu", "cpu"]

    # ④ core.config 不可用（ImportError）→ 保持默认 cpu
    monkeypatch.setitem(sys.modules, "core.config", None)
    det_page._load_model()
    assert devices == ["cuda", "cpu", "cpu", "cpu"]


@pytest.mark.unit
def test_load_model_engine_load_failure_status(det_page, tmp_path, monkeypatch):
    from gui.pages.predict import page as pred_mod

    class _Boom:
        def load(self, path, device="cpu"):
            raise ValueError("weights corrupt")

    _install_registry(monkeypatch, _Boom)
    monkeypatch.setattr(pred_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "m.pt"))
    det_page._load_model()
    assert any(t == "模型加载失败" and "weights corrupt" in a
               for t, a in det_page._msgs)
    assert det_page.lbl_model.text() == "加载失败"


# ============================== 单张推理尾巴 ============================== #
@pytest.mark.unit
def test_single_infer_cancelled_dialog(pred_page, monkeypatch):
    from gui.pages.predict import page as pred_mod

    pred_page._engine = type("E", (), {"infer": lambda self, im: _det_result(1)})()
    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: "")
    pred_page._single_infer()
    assert pred_page._msgs == []  # 取消：无"请先加载模型"也无失败
    assert pred_page.table.rowCount() == 0
    assert pred_page.btn_single.isEnabled() is True


@pytest.mark.unit
def test_single_done_pending_none_early_return(pred_page):
    pred_page.btn_single.setEnabled(False)
    pred_page._pending_single = None
    pred_page._single_done("x.png", 0.5)
    assert pred_page.btn_single.isEnabled() is True
    assert pred_page.btn_single.text() == "单张推理"
    assert pred_page.table.rowCount() == 0
    assert not any("分数" in a for _, a in pred_page._msgs)


@pytest.mark.unit
def test_single_done_audit_failure_swallowed(
    pred_page, fake_threads, tmp_path, monkeypatch, qapp
):
    """审计模块导入失败 → except Exception 吞掉，推理结果仍须落表。"""
    img = tmp_path / "img.png"
    _png(img)
    pred_page._engine = type("E", (), {"infer": lambda self, im: _det_result(1)})()
    from gui.pages.predict import page as pred_mod

    monkeypatch.setattr(pred_mod, "pick_open_file", lambda *a, **k: str(img))
    monkeypatch.setitem(sys.modules, "core.audit_logger", None)  # 审计导入炸

    pred_page._single_infer()  # 不得抛
    qapp.processEvents()
    assert pred_page.table.rowCount() == 1
    assert any("分数" in a for _, a in pred_page._msgs)


# ============================== 批量推理尾巴 ============================== #
@pytest.mark.unit
def test_batch_infer_cancelled_dialog(pred_page, monkeypatch):
    from gui.pages.predict import page as pred_mod

    pred_page._engine = type("E", (), {"infer": lambda self, im: _det_result(1)})()
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: "")
    pred_page._batch_infer()
    assert pred_page._msgs == []
    assert pred_page.btn_batch.isEnabled() is True
    assert pred_page.table.rowCount() == 0


@pytest.mark.unit
def test_batch_worker_per_image_path_and_cancel_breaks(
    pred_page, fake_threads, tmp_path, monkeypatch, qapp
):
    """无 infer_batch 的逐张路径 + 首张后取消：内层 break、第二批外层 break、
    进度仍上报、已完成结果照常落表/落 json。"""
    d = tmp_path / "many"
    d.mkdir()
    for i in range(17):  # > _BATCH_SIZE=16 → 两个外层批次
        _png(d / f"i{i:02d}.png")

    calls = []

    def _infer(self, im):
        calls.append(1)
        pred_page._batch_cancel = True  # 第一张推理后立即取消
        return _det_result(1)

    pred_page._engine = type("E", (), {"infer": _infer})()  # 无 infer_batch
    pred_page._project_dir = str(tmp_path)
    from gui.pages.predict import page as pred_mod

    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    pred_page._batch_infer()
    qapp.processEvents()

    assert len(calls) == 1  # 第 2 张内层 break；第 2 批（i=16）外层 break
    assert pred_page.table.rowCount() == 1
    assert any(t == "推理中" and a == "16/17" for t, a in pred_page._msgs)
    assert any(t == "批量完成" and a == "1/17" for t, a in pred_page._msgs)
    out = next((tmp_path / "results").glob("batchPredict_*/batch_results.json"))
    assert len(json.loads(out.read_text("utf-8"))) == 1


@pytest.mark.unit
def test_batch_worker_imread_fail_continue_and_infer_batch_swallowed(
    pred_page, fake_threads, tmp_path, monkeypatch, qapp, caplog
):
    d = tmp_path / "mix"
    d.mkdir()
    _png(d / "good.png")
    (d / "bad.png").write_bytes(b"not-an-image")

    class _Slow:  # 无 infer_batch → 逐张路径；坏图 imread None → continue
        def infer(self, im):
            return _det_result(1)

    pred_page._engine = _Slow()
    pred_page._project_dir = str(tmp_path)
    from gui.pages.predict import page as pred_mod

    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    pred_page._batch_infer()
    qapp.processEvents()
    assert pred_page.table.rowCount() == 1  # 坏图跳过，好图照常

    def _boom(self, paths):
        raise RuntimeError("batch boom")

    pred_page._engine = type("E", (), {"infer_batch": _boom})()
    pred_page.table.setRowCount(0)
    pred_page._results.clear()
    with caplog.at_level(logging.ERROR, logger="gui.pages.predict.page"):
        pred_page._batch_infer()
        qapp.processEvents()

    assert any("批量推理失败" in r.getMessage() for r in caplog.records)
    assert pred_page.table.rowCount() == 0  # 异常被吞，整批流程不中断
    assert any(t == "推理中" and a == "2/2" for t, a in pred_page._msgs)  # 进度仍上报
    assert any(t == "批量完成" and a == "0/2" for t, a in pred_page._msgs)


# ============================== _show_result 回退 ============================== #
@pytest.mark.unit
def test_show_result_sv_render_error_falls_back_to_legacy(
    pred_page, tmp_path, monkeypatch, caplog
):
    img = tmp_path / "img.png"
    _png(img, w=60, h=40)

    def _boom(imbgr, result, **kw):
        raise RuntimeError("sv boom")

    monkeypatch.setattr("inference.sv_bridge.render_result", _boom)
    with caplog.at_level(logging.WARNING, logger="gui.pages.predict.page"):
        pred_page._show_result(str(img), _det_result(2))

    assert any("sv 渲染失败" in r.getMessage() for r in caplog.records)
    pm = pred_page.preview.pixmap()
    assert pm is not None and not pm.isNull()  # legacy 画法仍出图


@pytest.mark.unit
def test_show_result_sv_bridge_import_error_falls_back(
    pred_page, tmp_path, monkeypatch, caplog
):
    img = tmp_path / "img.png"
    _png(img, w=60, h=40)
    monkeypatch.setitem(sys.modules, "inference.sv_bridge", None)  # 缺库
    with caplog.at_level(logging.WARNING, logger="gui.pages.predict.page"):
        pred_page._show_result(str(img), _det_result(1))

    assert any("supervision 未安装" in r.getMessage() for r in caplog.records)
    pm = pred_page.preview.pixmap()
    assert pm is not None and not pm.isNull()


@pytest.mark.unit
def test_show_result_unreadable_image_returns_without_pixmap(pred_page, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not-an-image")
    pred_page._show_result(str(bad), _det_result(1))
    pm = pred_page.preview.pixmap()
    assert pm is None or pm.isNull()  # Qt 原路径也读不出 → 早退不出图


# ============================== 导出尾巴 ============================== #
@pytest.mark.unit
def test_export_json_empty_and_cancelled(pred_page, tmp_path, monkeypatch):
    from gui.pages.predict import page as pred_mod

    pred_page._results = []
    pred_page._export_json()
    assert any(t == "无数据可导出" for t, _ in pred_page._msgs)

    pred_page._results = [
        {"file": "a.png", "task": "det", "score": 0.9,
         "boxes": [[1, 2, 3, 4]], "labels": ["crack"]},
    ]
    pred_page._msgs.clear()
    monkeypatch.setattr(pred_mod, "pick_save_file", lambda *a, **k: "")
    pred_page._export_json()
    assert pred_page._msgs == []  # 取消：无"已导出"
    assert not (tmp_path / "r.json").exists()


@pytest.mark.unit
def test_export_excel_empty_and_cancelled(pred_page, tmp_path, monkeypatch):
    from gui.pages.predict import page as pred_mod

    pred_page._results = []
    pred_page._export_excel()
    assert any(t == "无数据可导出" for t, _ in pred_page._msgs)

    pred_page._results = [
        {"file": "a.png", "task": "det", "score": 0.9,
         "boxes": [[1, 2, 3, 4]], "labels": ["crack"]},
    ]
    pred_page._msgs.clear()
    monkeypatch.setattr(pred_mod, "pick_save_file", lambda *a, **k: "")
    pred_page._export_excel()
    assert pred_page._msgs == []
    assert not (tmp_path / "r.xlsx").exists()
    assert not (tmp_path / "r.csv").exists()


@pytest.mark.unit
def test_export_excel_real_xlsx_two_sheets(pred_page, tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    from gui.pages.predict import page as pred_mod

    pred_page._results = [
        {"file": "a.png", "task": "det", "score": 0.91234,
         "boxes": [[1, 2, 3, 4], [5, 6, 7, 8]], "labels": ["crack", "hole"]},
        {"file": "b.png", "task": "det", "score": 0.4,
         "boxes": [], "labels": []},
        {"file": "=cmd.png", "task": "det", "score": 0.5,
         "boxes": [[1, 1, 2, 2]], "labels": []},
    ]
    xlsx = tmp_path / "r.xlsx"
    monkeypatch.setattr(pred_mod, "pick_save_file", lambda *a, **k: str(xlsx))
    pred_page._export_excel()
    assert any(t == "已导出" for t, _ in pred_page._msgs)

    wb = openpyxl.load_workbook(xlsx)
    assert wb.sheetnames == ["推理结果", "统计"]

    ws = wb["推理结果"]
    assert [c.value for c in ws[1]] == ["文件", "任务", "分数", "标签", "检测框数"]
    assert ws.max_row == 4  # 表头 + 3 数据行
    assert ws["A2"].value == "a.png"
    assert ws["C2"].value == 0.9123  # round(..., 4)
    assert ws["D2"].value == "crack, hole"
    assert ws["E2"].value == 2
    assert ws["E3"].value == 0
    assert ws["A4"].value == "'=cmd.png"  # 公式注入防护同样作用于 xlsx 单元格

    ws2 = wb["统计"]
    assert [ws2[f"A{r}"].value for r in range(2, 6)] == \
        ["总图像数", "总检测数", "缺陷图像数", "缺陷率"]
    assert ws2["B2"].value == 3
    assert ws2["B3"].value == 3  # 2 + 0 + 1 框
    assert ws2["B4"].value == 2  # a.png / =cmd.png 有框
    assert ws2["B5"].value == "66.7%"


# ============================== 统计/杂项尾巴 ============================== #
@pytest.mark.unit
def test_show_stats_empty_state(pred_page):
    pred_page._results = []
    pred_page._show_stats()
    assert any(t == "无数据可统计" for t, _ in pred_page._msgs)


@pytest.mark.unit
def test_retranslate_button_texts(pred_page):
    pred_page.retranslate()
    assert pred_page.btn_load_model.text() == "加载模型"
    assert pred_page.btn_single.text() == "单张推理"
    assert pred_page.btn_batch.text() == "批量推理"
    assert pred_page.btn_export_csv.text() == "导出CSV"
    assert pred_page.btn_export_json.text() == "导出JSON"
    assert pred_page.btn_export_excel.text() == "导出Excel"
    assert pred_page.btn_stats.text() == "统计报表"


# ============================== W13 C1：设备回灌 ============================== #
@pytest.mark.unit
def test_load_model_device_reads_user_settings(det_page, tmp_path, monkeypatch):
    """W13 C1（RED→GREEN）：设置页持久化的 device 必须回灌 predict 设备解析。

    写 user_settings.json {"device": "cpu"}（路径注入 gui.core.settings_io.CONFIG_DIR，
    沿用 settings 页 _CONFIG_DIR 注入模式）→ 经生产设备解析路径应得 "cpu"。
    修复前 predict 恒读 core.config 默认 "cuda"（cuda 可用时保持）→ 本用例必红。
    """
    pytest.importorskip("torch")
    from gui.pages.predict import page as pred_mod

    (tmp_path / "user_settings.json").write_text(
        json.dumps({"device": "cpu"}), encoding="utf-8")
    try:
        import gui.core.settings_io as sio
    except ImportError:  # 修复前模块不存在：跳过注入，用行为红证明 bug
        sio = None
    if sio is not None:
        monkeypatch.setattr(sio, "CONFIG_DIR", tmp_path)

    devices = []

    class _Eng:
        def load(self, path, device="cpu"):
            devices.append(device)

    _install_registry(monkeypatch, _Eng)
    monkeypatch.setattr(pred_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "m.pt"))
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)

    det_page._load_model()
    assert devices == ["cpu"]


@pytest.mark.unit
def test_load_model_device_user_settings_absent_keeps_chain(
    det_page, tmp_path, monkeypatch
):
    """无 user_settings.json / 无 device 键 → 回退 cuda 链语义保持。"""
    pytest.importorskip("torch")
    from gui.pages.predict import page as pred_mod
    import gui.core.settings_io as sio

    empty = tmp_path / "no_settings"
    empty.mkdir()
    monkeypatch.setattr(sio, "CONFIG_DIR", empty)

    devices = []

    class _Eng:
        def load(self, path, device="cpu"):
            devices.append(device)

    _install_registry(monkeypatch, _Eng)
    monkeypatch.setattr(pred_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "m.pt"))

    # 无设置文件 → cuda；cuda 可用 → 保持 cuda
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    det_page._load_model()
    assert devices == ["cuda"]

    # 无设置文件 → cuda；cuda 不可用 → 回退 cpu
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    det_page._load_model()
    assert devices == ["cuda", "cpu"]

    # 有设置文件但无 device 键 → 仍走 cuda 链（可用 → cuda）
    (empty / "user_settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    det_page._load_model()
    assert devices == ["cuda", "cpu", "cuda"]


@pytest.mark.unit
def test_load_model_device_invalid_user_setting_ignored(
    det_page, tmp_path, monkeypatch
):
    """手改出的非法 device 值按未设置处理（回退 cuda 链）。"""
    pytest.importorskip("torch")
    from gui.pages.predict import page as pred_mod
    import gui.core.settings_io as sio

    monkeypatch.setattr(sio, "CONFIG_DIR", tmp_path)
    (tmp_path / "user_settings.json").write_text(
        json.dumps({"device": "tpu999"}), encoding="utf-8")

    devices = []

    class _Eng:
        def load(self, path, device="cpu"):
            devices.append(device)

    _install_registry(monkeypatch, _Eng)
    monkeypatch.setattr(pred_mod, "pick_open_file",
                        lambda *a, **k: str(tmp_path / "m.pt"))
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)

    det_page._load_model()
    assert devices == ["cuda"]  # 非法值忽略 → 默认链 → cuda 可用保持
