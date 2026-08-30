"""W33（W26 计划 P2）：batchPredict 产物补齐——masks 持久化 + 叠加图 + 对象类型过滤。

现状批量 seg 的 masks 不可恢复（只存 boxes-JSON）——工业工具真缺陷；
SKolpha「阈值+对象类型」双参对标的收尾（阈值 W28 已接，本轮过滤）。
输出根可配置：经设置页 workspace 单源（W28 已建，test_w28 留有守卫）。
"""
from __future__ import annotations

import base64
import json

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeMsgBox:
    Information = 1

    def __init__(self, *a, **k):
        pass

    def setIcon(self, *a):
        pass

    def setWindowTitle(self, *a):
        pass

    def setText(self, *a):
        pass

    def exec(self):
        return 0


# ============================== 1. 对象类型过滤（纯函数） ============================== #


@pytest.mark.unit
def test_filter_result_by_labels_keeps_alignment():
    """标签过滤：boxes/labels/scores/masks 协同保留；空集=None 透传。"""
    from gui.pages.predict.workers import filter_result_by_labels

    masks = np.zeros((3, 8, 8), dtype=bool)
    masks[0, 0:4, 0:4] = True  # crack #0 的掩码（须随过滤保留）
    masks[1] = True            # hole（整行被滤）
    result = DetectionResult(
        task=TaskType.SEG, score=0.9,
        boxes=((1, 1, 5, 5), (2, 2, 6, 6), (3, 3, 7, 7)),
        labels=("crack", "hole", "crack"),
        scores=(0.9, 0.8, 0.7),
        masks=masks,
    )
    got = filter_result_by_labels(result, {"crack"})
    assert got.labels == ("crack", "crack")
    assert got.boxes == ((1, 1, 5, 5), (3, 3, 7, 7))
    assert got.scores == (0.9, 0.7)
    assert got.masks.shape == (2, 8, 8)
    assert got.masks[0][0:4, 0:4].all(), "crack #0 掩码须随索引协同保留"
    assert not got.masks[1].any(), "原 #2（全 False）占位正确"

    # 空/None 过滤集 → 原样语义（新对象，内容等价）
    assert filter_result_by_labels(result, None).labels == result.labels
    assert filter_result_by_labels(result, set()).labels == result.labels


# ============================== 2. masks 落盘 ============================== #


@pytest.mark.unit
def test_batch_writes_masks_rle_for_seg(qapp, fake_threads, tmp_path, monkeypatch):
    """批量 seg：masks 经 RLE 落盘（可恢复——现状批量 seg masks 丢失）。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage

    d = tmp_path / "batch"
    d.mkdir()
    (d / "a.png").write_bytes(PNG_1PX)

    masks = np.zeros((2, 8, 8), dtype=bool)
    masks[0, 0:4, 0:4] = True

    class _SegEngine:
        def infer(self, img, threshold=0.5, labels=None):
            return DetectionResult(
                task=TaskType.SEG, score=0.9,
                boxes=((1, 1, 5, 5), (2, 2, 6, 6)),
                labels=("crack", "hole"), scores=(0.9, 0.8),
                masks=masks,
            )

    page = PredictPage()
    page._engine = _SegEngine()
    page._project_dir = str(tmp_path)
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    page._batch_infer()
    qapp.processEvents()

    mask_files = list((tmp_path / "results").rglob("masks_*.npz"))
    assert mask_files, "批量 seg 应落盘 masks（RLE 持久化）"
    # RLE 可恢复性：解码回 mask 形状一致
    import numpy as _np

    from serving.mask_codec import decode_mask_rle

    blob = _np.load(mask_files[0], allow_pickle=True)
    keys = sorted(blob.files)
    assert keys, "npz 须按实例存 RLE"
    decoded = decode_mask_rle(blob[keys[0]], (8, 8))
    assert decoded.shape == (8, 8)
    assert bool(decoded[0:4, 0:4].all())


# ============================== 3. 可选叠加图 ============================== #


@pytest.mark.unit
def test_batch_overlay_written_when_checked(qapp, fake_threads, tmp_path, monkeypatch):
    """勾选「保存叠加图」→ 批量产物含 overlay_*（sv_bridge 渲染）。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage

    d = tmp_path / "batch"
    d.mkdir()
    (d / "a.png").write_bytes(PNG_1PX)

    class _Engine:
        def infer(self, img, threshold=0.5, labels=None):
            return DetectionResult(
                task=TaskType.DET, score=0.9,
                boxes=((1, 1, 5, 5),), labels=("crack",), scores=(0.9,),
            )

    page = PredictPage()
    page._engine = _Engine()
    page._project_dir = str(tmp_path)
    page.chk_overlay.setChecked(True)  # W33 叠加图开关
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)
    monkeypatch.setattr(
        pred_mod, "render_result",
        lambda img, result: np.full((8, 8, 3), 200, np.uint8),
    )

    page._batch_infer()
    qapp.processEvents()

    overlays = list((tmp_path / "results").rglob("overlay_*"))
    assert overlays, "勾选后应产出叠加结果图"


# ============================== 4. 过滤接线（页面） ============================== #


@pytest.mark.unit
def test_batch_label_filter_applies_to_records(qapp, fake_threads, tmp_path, monkeypatch):
    """标签过滤输入接线：填 crack → 批量记录只含 crack（全标签被滤时不记行）。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage

    d = tmp_path / "batch"
    d.mkdir()
    (d / "a.png").write_bytes(PNG_1PX)

    class _Engine:
        def infer(self, img, threshold=0.5, labels=None):
            return DetectionResult(
                task=TaskType.DET, score=0.9,
                boxes=((1, 1, 5, 5), (2, 2, 6, 6)),
                labels=("crack", "hole"), scores=(0.9, 0.8),
            )

    page = PredictPage()
    page._engine = _Engine()
    page._project_dir = str(tmp_path)
    page.edit_label_filter.setText("crack")  # W33 对象类型过滤
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    page._batch_infer()
    qapp.processEvents()

    assert page._results, "crack 行应保留"
    for r in page._results:
        assert r["labels"] == ["crack"], r
    out = next((tmp_path / "results").glob("batchPredict_*/batch_results.json"))
    assert all(r["labels"] == ["crack"] for r in json.loads(out.read_text("utf-8")))


# ============================== 5. permissions 面更新 ============================== #


@pytest.mark.unit
def test_batch_infer_action_registered():
    """W33 permissions 面更新：predict.batch_infer 三角色（operator 推理页可见）。"""
    from gui.core.permissions import ROLES, action_allowed

    for role in ROLES:
        assert action_allowed(role, "predict.batch_infer") is True, role
