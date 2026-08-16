"""eval 页（gui/pages/eval_）行为测试（W8-T2：36% → 洼地填平）。

覆盖 _run_eval 全分支（参数校验 / fid·lpips 生成式 / supervised 引擎可用与
回退 GT 自比较 / seg·abdet 崩溃路径防卡死）、三槽、ConfusionMatrixWidget
自绘（offscreen grab() 触发 paintEvent）。
"""
from __future__ import annotations

import json
import os
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
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


@pytest.fixture
def eval_page(qapp):
    from gui.pages.eval_.page import EvalPage

    page = EvalPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


def _labelme(path, name="a.png", box=(4, 4, 20, 16)):
    path.write_text(
        json.dumps({
            "imagePath": name,
            "shapes": [{"label": "crack", "shape_type": "rectangle",
                        "points": [[box[0], box[1]], [box[2], box[3]]]}],
        }),
        encoding="utf-8",
    )


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


# ============================== 参数校验 ============================== #
@pytest.mark.unit
def test_run_eval_requires_model_then_gt(eval_page):
    eval_page._run_eval()
    assert any("模型权重" in t for t, _ in eval_page._msgs)

    eval_page._model_edit.setText("fake.pt")
    eval_page._run_eval()
    assert any("标注目录" in t for t, _ in eval_page._msgs)


@pytest.mark.unit
def test_pick_model_and_gt_fill_edits(eval_page, monkeypatch, tmp_path):
    from gui.pages.eval_ import page as eval_mod

    monkeypatch.setattr(eval_mod, "pick_open_file", lambda *a, **k: str(tmp_path / "m.pt"))
    monkeypatch.setattr(eval_mod, "pick_directory", lambda *a, **k: str(tmp_path / "gt"))
    eval_page._pick_model()
    eval_page._pick_gt()
    assert eval_page._model_edit.text().endswith("m.pt")
    assert eval_page._gt_edit.text().endswith("gt")


# ============================== 槽与混淆矩阵 ============================== #
@pytest.mark.unit
def test_set_results_slot_builds_confusion_from_tp_fp_fn(qapp):
    from gui.pages.eval_.page import ConfusionMatrixWidget, EvalPage

    page = EvalPage()
    page._eval_progress.setVisible(True)
    page._run_btn.setEnabled(False)
    page._set_results_slot([
        ("TP", "10", "n"), ("FP", "2", "n"), ("FN", "3", "n"), ("TN", "45", "n"),
        ("mAP", "0.9000", "n"), ("FID", "N/A", "n"),  # N/A 不得炸 float()
    ])
    assert page._confusion._matrix == [[10, 2], [3, 45]]
    assert page._eval_progress.isVisible() is False
    assert page._run_btn.isEnabled() is True
    assert page._table.rowCount() == 6  # 含 N/A 行（FID 不解析进混淆矩阵但占表行）
    assert page._table.item(0, 0).text() == "TP"

    # 无 TP/FP/FN → 示例矩阵兜底
    page._set_results_slot([("mAP", "0.5", "n")])
    assert page._confusion._matrix == [[1, 0], [0, 1]]


@pytest.mark.unit
def test_eval_failed_slot_restores_ui(eval_page):
    eval_page._run_btn.setEnabled(False)
    eval_page._eval_progress.setVisible(True)
    eval_page._eval_failed_slot("x" * 100)
    assert eval_page._run_btn.isEnabled() is True
    assert eval_page._eval_progress.isVisible() is False
    assert eval_page._msgs[-1][0] == "评估失败"
    assert len(eval_page._msgs[-1][1]) == 60  # msg[:60]


@pytest.mark.unit
def test_confusion_widget_paint_offscreen(qapp):
    from gui.pages.eval_.page import ConfusionMatrixWidget

    w = ConfusionMatrixWidget()
    w.set_title("混淆矩阵")
    w.resize(320, 260)
    w.set_matrix([[50, 2], [3, 45]], ["缺陷", "正常"])
    assert not w.grab().isNull()  # 触发 paintEvent 自绘

    w.clear_matrix()
    assert w._matrix == []
    assert not w.grab().isNull()  # 空矩阵 → "无评估数据" 分支


@pytest.mark.unit
def test_retranslate_refresh_texts(eval_page):
    eval_page.retranslate()
    assert eval_page._title.text() == "模型评估"
    assert eval_page._run_btn.text() == "开始评估"


# ============================== supervised 分支 ============================== #
@pytest.mark.unit
def test_run_eval_det_engine_unavailable_falls_back(
    eval_page, fake_threads, monkeypatch, tmp_path, qapp
):
    """引擎加载失败 → 警告 + GT 自比较（mAP=1.0）+ 进度推进到 100。"""
    import models.supervised.registry as reg_mod

    gt = tmp_path / "gt"
    gt.mkdir()
    for i in range(6):  # 6 个文件 → 触发 idx%5==0 进度上报（首+尾）
        _labelme(gt / f"{i}.json", f"{i}.png")

    def _boom(enum_val):
        raise RuntimeError("no engine")

    monkeypatch.setattr(reg_mod, "get_engine", _boom)

    eval_page._model_edit.setText("fake.pt")
    eval_page._gt_edit.setText(str(gt))
    eval_page._run_eval()
    qapp.processEvents()

    assert any("评估引擎不可用" in t for t, _ in eval_page._msgs)
    assert eval_page._eval_progress.value() == 100  # 末次上报 int(6/6*100)
    assert eval_page._table.rowCount() == 2
    texts = [eval_page._table.item(i, 0).text() for i in range(2)]
    assert texts == ["class_0", "mAP"]
    assert all(eval_page._table.item(i, 1).text() == "1.0000" for i in range(2))
    assert any(t == "评估完成" for t, _ in eval_page._msgs)


@pytest.mark.unit
def test_run_eval_det_engine_infer_path(
    eval_page, fake_threads, monkeypatch, tmp_path, qapp
):
    """引擎可用 → 用引擎推理结果（而非 GT）作为预测。"""
    import models.supervised.registry as reg_mod

    gt = tmp_path / "gt"
    gt.mkdir()
    _png(gt / "a.png")
    _labelme(gt / "a.json", "a.png")

    infer_calls = []

    class _Result:
        boxes = np.array([[4.0, 4.0, 20.0, 16.0]])
        score = 0.9

    class _Engine:
        def load(self, path, device="cpu"):
            pass

        def infer(self, img_path):
            infer_calls.append(img_path)
            return _Result()

    monkeypatch.setattr(reg_mod, "get_engine", lambda enum_val: _Engine())

    eval_page._model_edit.setText("m.pt")
    eval_page._gt_edit.setText(str(gt))
    eval_page._run_eval()
    qapp.processEvents()

    assert infer_calls == [str(gt / "a.png")]  # 相对 imagePath → 绝对路径
    assert eval_page._table.rowCount() == 2
    assert eval_page._table.item(1, 1).text() == "1.0000"  # mAP：IoU=1 自匹配


@pytest.mark.unit
def test_run_eval_det_no_json_rows_na(eval_page, fake_threads, tmp_path, qapp):
    gt = tmp_path / "gt"
    gt.mkdir()
    eval_page._model_edit.setText("m.pt")
    eval_page._gt_edit.setText(str(gt))
    eval_page._run_eval()
    qapp.processEvents()
    assert eval_page._table.rowCount() == 1
    assert eval_page._table.item(0, 1).text() == "N/A"


@pytest.mark.unit
def test_run_eval_seg_and_abdet_must_not_hang_ui(
    eval_page, fake_threads, monkeypatch, tmp_path, qapp
):
    """seg/abdet 指标吃矩形 dict 数据会 TypeError——不得让 worker 裸死、
    按钮卡禁用（RED：当前 except 元组缺 TypeError，异常穿透线程）。"""
    import models.supervised.registry as reg_mod

    monkeypatch.setattr(reg_mod, "get_engine",
                        lambda enum_val: (_ for _ in ()).throw(RuntimeError()))
    gt = tmp_path / "gt"
    gt.mkdir()
    _labelme(gt / "a.json", "a.png")
    _labelme(gt / "b.json", "b.png")

    eval_page._model_edit.setText("m.pt")
    eval_page._gt_edit.setText(str(gt))
    for metric_idx in (1, 2):  # seg / abdet
        eval_page._metric_combo.setCurrentIndex(metric_idx)
        eval_page._run_btn.setEnabled(False)
        eval_page._run_eval()  # FakeThread 同步执行：裸异常会直接穿透本调用
        qapp.processEvents()
        assert eval_page._run_btn.isEnabled() is True, f"metric={metric_idx} 后按钮必须恢复"
        assert any(t == "评估失败" for t, _ in eval_page._msgs), f"metric={metric_idx} 须显式失败"


# ============================== 生成式分支（fid/lpips） ============================== #
@pytest.mark.unit
def test_run_eval_fid_and_lpips(
    eval_page, fake_threads, monkeypatch, tmp_path, qapp
):
    import evaluation.generative_metrics as gm

    gt = tmp_path / "gt"
    gt.mkdir()
    _png(gt / "r1.png")
    gen_img = tmp_path / "gen1.png"
    _png(gen_img)

    monkeypatch.setattr(gm, "fid_score", lambda g, r: 12.0)
    monkeypatch.setattr(gm, "perceptual_loss", lambda g, r: 0.25)

    # FID：idx 3；model 为单文件路径（非目录 → [model]）
    eval_page._metric_combo.setCurrentIndex(3)
    eval_page._model_edit.setText(str(gen_img))
    eval_page._gt_edit.setText(str(gt))
    eval_page._run_eval()
    qapp.processEvents()
    assert eval_page._table.rowCount() == 1
    assert eval_page._table.item(0, 0).text() == "FID"
    assert eval_page._table.item(0, 1).text() == "12.00"

    # LPIPS：idx 4
    eval_page._table.setRowCount(0)
    eval_page._metric_combo.setCurrentIndex(4)
    eval_page._run_eval()
    qapp.processEvents()
    assert eval_page._table.rowCount() == 1
    assert eval_page._table.item(0, 0).text() == "LPIPS"
    assert eval_page._table.item(0, 1).text() == "0.2500"


@pytest.mark.unit
def test_run_eval_fid_empty_real_images_no_rows(
    eval_page, fake_threads, monkeypatch, tmp_path, qapp
):
    import evaluation.generative_metrics as gm

    called = []
    monkeypatch.setattr(gm, "fid_score", lambda g, r: called.append((g, r)) or 0.0)

    gt = tmp_path / "gt"  # 空目录 → real_imgs 为空 → 不计算
    gt.mkdir()
    eval_page._metric_combo.setCurrentIndex(3)
    eval_page._model_edit.setText(str(tmp_path / "g.png"))
    eval_page._gt_edit.setText(str(gt))
    eval_page._run_eval()
    qapp.processEvents()
    assert called == []
    assert eval_page._table.rowCount() == 0
    assert any(t == "评估完成" for t, _ in eval_page._msgs)
