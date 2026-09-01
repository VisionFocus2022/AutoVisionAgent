"""W44：留档候选清偿——C SAM AMG 自动标注 + B SAM 笔刷精修。

取证依据（docs/skolpha-sam-annotation-forensics.md §6）：
- AMG：原品预测页自动标注 = SamAutomaticMaskGenerator + thresh_iou 过滤
- 笔刷：labelme Canvas paint_to_shape——笔划采样为点提示 + mask_input 迭代
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from labeling.base import AnnotationMode
from labeling.sam_adapter import SamAdapter

_DUMMY_IMG = np.zeros((64, 64, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _sq(y, x, s):
    m = np.zeros((64, 64), dtype=bool)
    m[y:y + s, x:x + s] = True
    return m


# ============================== C：AMG 自动标注 ============================== #


def _amg_stub(monkeypatch, anns):
    """stub segment_anything.SamAutomaticMaskGenerator（记录构造参数）。"""
    adapter = SamAdapter()
    adapter._predictor = MagicMock()
    adapter._predictor.model = object()
    made = {}

    class _FakeGen:
        def __init__(self, sam, pred_iou_thresh=0.88, min_mask_region_area=0):
            made["iou"] = pred_iou_thresh
            made["min_area"] = min_mask_region_area
            made["sam"] = sam

        def generate(self, image):
            return anns

    fake_mod = types.ModuleType("segment_anything")
    fake_mod.SamAutomaticMaskGenerator = _FakeGen
    monkeypatch.setitem(sys.modules, "segment_anything", fake_mod)
    return adapter, made


class TestBuildAmgDetector:

    def test_shapes_sorted_capped_and_polygons(self, monkeypatch):
        anns = [
            {"segmentation": _sq(2, 2, 10), "area": 100},   # 小
            {"segmentation": _sq(2, 2, 30), "area": 900},   # 大
            {"segmentation": _sq(2, 2, 20), "area": 400},   # 中
        ]
        adapter, made = _amg_stub(monkeypatch, anns)
        detector = adapter.build_amg_detector(
            iou_thresh=0.88, min_area=64, max_masks=2, label="crack"
        )
        assert made["iou"] == 0.88 and made["min_area"] == 64
        assert made["sam"] is adapter._predictor.model
        shapes = detector(_DUMMY_IMG)
        assert len(shapes) == 2, "max_masks 截断"
        assert all(s.mode == AnnotationMode.POLYGON for s in shapes)
        assert all(len(s.points) >= 3 for s in shapes)
        assert all(s.label == "crack" for s in shapes)
        # 面积降序（大→中，小被截断）
        a1 = _area(shapes[0])
        a2 = _area(shapes[1])
        assert a1 > a2

    def test_empty_result(self, monkeypatch):
        adapter, _ = _amg_stub(monkeypatch, [])
        assert adapter.build_amg_detector()(_DUMMY_IMG) == []


def _area(shape):
    xs = [p[0] for p in shape.points]
    ys = [p[1] for p in shape.points]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


class TestAutoModeWiring:

    def test_controller_attach_detector(self, qapp):
        from labeling.canvas import AnnotationCanvas
        from labeling.controller import AnnotationController

        ctrl = AnnotationController(
            AnnotationCanvas(), mode=AnnotationMode.AUTO, label="d"
        )
        assert ctrl.attach_detector(lambda img: [], _DUMMY_IMG) is True

    def test_controller_attach_detector_wires_result_hook(self, qapp):
        """W55（FR-002）：on_result 经 attach_detector 透传到
        AutoLabeler 结果回调——0 形状时页面据此发降级提示。"""
        from labeling.canvas import AnnotationCanvas
        from labeling.controller import AnnotationController

        ctrl = AnnotationController(
            AnnotationCanvas(), mode=AnnotationMode.AUTO, label="d"
        )
        got: list[int] = []
        assert ctrl.attach_detector(
            lambda img: [], _DUMMY_IMG, on_result=got.append
        ) is True
        ctrl._labeler.on_press((0, 0))
        assert got == [0], "on_result 应透传到结果回调（0 形状即回调 0）"

    def test_entering_auto_triggers_sam_setup(self, qapp, monkeypatch):
        from gui.pages.label.page import LabelPage

        page = LabelPage()
        called = []
        monkeypatch.setattr(page, "_ensure_sam", lambda: called.append(1))
        page._apply_mode(AnnotationMode.AUTO)
        assert called == [1], "进入 AUTO 应触发 _ensure_sam"


# ============================== B：predict_points（多点+迭代） ============================== #


class TestPredictPoints:

    def _adapter(self):
        adapter = SamAdapter()
        adapter._predictor = MagicMock()
        adapter._predictor.predict.return_value = (
            np.array([_sq(8, 8, 30)]), np.array([0.9]), "LOGITS_X",
        )
        return adapter

    def test_multi_points_and_mask_input_passthrough(self):
        adapter = self._adapter()
        poly, logits = adapter.predict_points(
            _DUMMY_IMG, [(10, 10), (20, 20)], [1, 1],
            box=None, mask_input="PREV",
        )
        kw = adapter._predictor.predict.call_args.kwargs
        assert kw["point_coords"].shape == (2, 2)
        assert kw["point_labels"].tolist() == [1, 1]
        assert kw["mask_input"] == "PREV", "上轮 logits 须透传（迭代精修）"
        assert logits == "LOGITS_X", "本轮 logits 须回传"
        assert len(poly) >= 3

    def test_no_mask_input_when_none(self):
        adapter = self._adapter()
        adapter.predict_points(_DUMMY_IMG, [(10, 10)], [1])
        assert adapter._predictor.predict.call_args.kwargs.get("mask_input") is None


# ============================== B：BrushSamLabeler ============================== #


class _FakeBrushAdapter:
    def __init__(self):
        self.calls = []
        self.n = 0

    def predict_points(self, image, points, labels, box=None, mask_input=None):
        self.n += 1
        self.calls.append((list(points), list(labels), box, mask_input))
        poly = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0)]
        return list(poly), f"LOGITS_{self.n}"


class TestBrushSamLabeler:

    def _labeler(self, adapter):
        from labeling.modes.brush_sam import BrushSamLabeler

        return BrushSamLabeler("defect", sam_adapter=adapter, image=_DUMMY_IMG)

    def test_stroke_accumulates_and_iterates(self):
        fake = _FakeBrushAdapter()
        lab = self._labeler(fake)
        # 笔划1：(10,10)→(18,18)（采样点距≥4px）
        lab.on_press((10, 10))
        lab.on_move((12, 12))
        lab.on_move((18, 18))
        lab.on_release((18, 18))
        assert len(fake.calls) == 1
        pts1, labels1, _, mask_in1 = fake.calls[0]
        assert len(pts1) >= 2, "拖划采样应≥2 点"
        assert labels1 and all(v == 1 for v in labels1)
        assert mask_in1 is None, "首笔无迭代输入"
        # 笔划2：携笔划1 logits + 累积点
        lab.on_press((30, 30))
        lab.on_move((36, 36))
        lab.on_release((36, 36))
        assert len(fake.calls) == 2
        pts2, _, _, mask_in2 = fake.calls[1]
        assert mask_in2 == "LOGITS_1", "第二笔须携上轮 logits 迭代"
        assert len(pts2) > len(pts1), "点应跨笔划累积"
        assert any(p == (10, 10) for p in pts2), "笔划1 的点须保留在累积集"

    def test_commit_and_reset(self):
        fake = _FakeBrushAdapter()
        lab = self._labeler(fake)
        lab.on_press((10, 10))
        lab.on_release((10, 10))
        shape = lab.commit()
        assert shape is not None and shape.mode == AnnotationMode.POLYGON
        assert lab.commit() is None
        lab.reset()
        lab.on_press((40, 40))
        lab.on_release((40, 40))
        # reset 后：无迭代输入（logits 清）、点集不含旧点
        _, _, _, mask_in = fake.calls[-1]
        assert mask_in is None

    def test_mode_registered_and_button(self, qapp):
        from gui.pages.label.page import LabelPage
        from labeling.modes import make_labeler

        assert AnnotationMode.SAM_BRUSH.value == "sam_brush"
        assert make_labeler(AnnotationMode.SAM_BRUSH, "d") is not None
        page = LabelPage()
        assert AnnotationMode.SAM_BRUSH in page._mode_btns
