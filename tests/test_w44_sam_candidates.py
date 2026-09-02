"""W44 留档候选清偿——适配器层存活部分（2026-09-01 模式裁剪后）。

保留：TestBuildAmgDetector / TestPredictPoints（sam_adapter 库级 API，
无 UI 模式依赖，供批量流程复用）。
已删：TestAutoModeWiring（AUTO 模式接线）、TestBrushSamLabeler（SAM 笔刷
模式）——模式本体随极柱工作流裁剪移除，见 docs/prd-labeling-mode-prune.md。

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
