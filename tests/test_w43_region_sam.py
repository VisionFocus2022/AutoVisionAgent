"""W43：矩形区域 SAM 分割（SKolpha 取证报告 §5 映射实现）。

机制（docs/skolpha-sam-annotation-forensics.md）：
矩形=box prompt 与点击 point 同传 → 掩码∩矩形硬约束（原品
intersect_merge_mask 语义）→ findContours+ε 折点 → 多边形 Shape。
交互：拖拽定/重设区域 → 区域内单击分割 → 双击/回车提交。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from labeling.base import AnnotationMode
from labeling.sam_adapter import SamAdapter

_DUMMY_IMG = np.zeros((64, 64, 3), dtype=np.uint8)
_BOX = (8, 8, 40, 40)


def _crossing_blob_adapter():
    """stub predictor：圆盘 blob 跨越矩形边界（证明硬约束必需）。"""
    adapter = SamAdapter()
    adapter._predictor = MagicMock()
    yy, xx = np.mgrid[0:64, 0:64]
    # 圆心(20,24) r=18：底部/右侧越出 [8,40] 矩形
    mask = (xx - 20) ** 2 + (yy - 24) ** 2 <= 18 ** 2
    adapter._predictor.predict.return_value = (
        np.array([mask]), np.array([0.9]), None,
    )
    return adapter, adapter._predictor


# ============================== 1. adapter：组合 prompt + 硬约束 ============================== #


class TestPredictPointInBox:

    def test_point_and_box_both_passed(self):
        """矩形须作为 box prompt 与点击 point 同传（原品 ai_predict 签名）。"""
        adapter, pred = _crossing_blob_adapter()
        adapter.predict_point_in_box(_DUMMY_IMG, (20, 24), _BOX)
        kw = pred.predict.call_args.kwargs
        assert kw.get("point_coords") is not None
        assert kw.get("point_labels") is not None
        assert kw.get("box") is not None, "矩形未作为 box prompt 同传"

    def test_polygon_clipped_inside_box(self):
        """跨界 blob 被硬约束：折点全部落在矩形内（∩矩形证明）。"""
        adapter, _ = _crossing_blob_adapter()
        poly = adapter.predict_point_in_box(_DUMMY_IMG, (20, 24), _BOX)
        assert len(poly) >= 3, "区域内应检出多边形"
        x1, y1, x2, y2 = _BOX
        assert all(x1 <= x <= x2 and y1 <= y <= y2 for x, y in poly), (
            f"折点越出矩形（硬约束失效）: {poly}"
        )

    def test_empty_mask_returns_empty(self):
        adapter, _ = _crossing_blob_adapter()
        adapter._predictor.predict.return_value = (
            np.zeros((1, 64, 64), dtype=bool), np.array([0.9]), None,
        )
        assert adapter.predict_point_in_box(_DUMMY_IMG, (20, 24), _BOX) == []


# ============================== 2. RegionSamLabeler 交互 ============================== #


class _FakeAdapter:
    """记录调用的假适配器。"""

    def __init__(self):
        self.calls = []
        self.result = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]

    def predict_point_in_box(self, image, point, box):
        self.calls.append((tuple(point), tuple(box)))
        return list(self.result)


class TestRegionSamLabeler:

    def _labeler(self, adapter=None):
        from labeling.modes.region_sam import RegionSamLabeler

        return RegionSamLabeler("defect", sam_adapter=adapter, image=_DUMMY_IMG)

    def test_mode_enum_and_factory(self):
        assert AnnotationMode.REGION_SAM.value == "region_sam"
        from labeling.modes import make_labeler

        lab = make_labeler(AnnotationMode.REGION_SAM, "defect")
        assert lab is not None

    def test_drag_sets_region_click_inside_predicts(self):
        fake = _FakeAdapter()
        lab = self._labeler(fake)
        lab.on_press((10, 10))
        lab.on_move((50, 50))
        lab.on_release((50, 50))
        assert fake.calls == [], "拖拽阶段不得触发预测"
        lab.on_press((20, 20))
        lab.on_release((20, 20))
        assert len(fake.calls) == 1
        pt, box = fake.calls[0]
        assert pt == (20, 20), "点击点须原样传入"
        assert box == (10, 10, 50, 50), "区域矩形须作为 box 传入"

    def test_click_outside_region_ignored(self):
        fake = _FakeAdapter()
        lab = self._labeler(fake)
        lab.on_press((10, 10))
        lab.on_release((50, 50))
        lab.on_press((60, 60))
        lab.on_release((60, 60))
        assert fake.calls == [], "区域外单击应忽略"

    def test_click_before_region_ignored(self):
        fake = _FakeAdapter()
        lab = self._labeler(fake)
        lab.on_press((20, 20))
        lab.on_release((20, 20))
        assert fake.calls == [], "未定区域先单击应忽略"

    def test_commit_returns_polygon_then_empty(self):
        fake = _FakeAdapter()
        lab = self._labeler(fake)
        lab.on_press((10, 10))
        lab.on_release((50, 50))
        lab.on_press((20, 20))
        lab.on_release((20, 20))
        shape = lab.commit()
        assert shape is not None
        assert shape.mode == AnnotationMode.POLYGON
        assert len(shape.points) >= 3
        assert lab.commit() is None, "提交后 pending 应清空"

    def test_preview_region_rect_while_dragging(self):
        lab = self._labeler(None)
        lab.on_press((10, 10))
        lab.on_move((40, 30))
        p = lab.preview()
        assert p is not None and p.mode == AnnotationMode.RECTANGLE

    def test_redrag_replaces_region(self):
        fake = _FakeAdapter()
        lab = self._labeler(fake)
        lab.on_press((10, 10))
        lab.on_release((50, 50))
        lab.on_press((5, 5))
        lab.on_release((25, 25))
        lab.on_press((15, 15))
        lab.on_release((15, 15))
        assert fake.calls[0][1] == (5, 5, 25, 25), "重拖拽应替换区域"

    def test_reset_clears_region(self):
        fake = _FakeAdapter()
        lab = self._labeler(fake)
        lab.on_press((10, 10))
        lab.on_release((50, 50))
        lab.reset()
        lab.on_press((20, 20))
        lab.on_release((20, 20))
        assert fake.calls == [], "reset 后区域应清除"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ============================== 3. controller 扩展 ============================== #


class TestControllerAttachRegionSam:

    def test_attach_accepts_region_sam(self, qapp):
        from labeling.canvas import AnnotationCanvas
        from labeling.controller import AnnotationController

        ctrl = AnnotationController(
            AnnotationCanvas(), mode=AnnotationMode.REGION_SAM, label="defect"
        )
        assert ctrl.attach_interactive(object(), _DUMMY_IMG) is True

    def test_attach_interactive_behavior_unchanged(self, qapp):
        from labeling.canvas import AnnotationCanvas
        from labeling.controller import AnnotationController

        ctrl = AnnotationController(
            AnnotationCanvas(), mode=AnnotationMode.INTERACTIVE, label="d"
        )
        assert ctrl.attach_interactive(object(), _DUMMY_IMG) is True


# ============================== 4. 页面接线 ============================== #


class TestPageWiring:

    def test_mode_button_present_and_switchable(self, qapp, monkeypatch):
        from gui.pages.label.page import LabelPage

        page = LabelPage()
        assert AnnotationMode.REGION_SAM in page._mode_btns, "SAM 区域按钮缺失"
        monkeypatch.setattr(page, "_ensure_sam", lambda: None)
        page._apply_mode(AnnotationMode.REGION_SAM)
        assert page.controller.mode is AnnotationMode.REGION_SAM

    def test_entering_mode_triggers_sam_setup(self, qapp, monkeypatch):
        from gui.pages.label.page import LabelPage

        page = LabelPage()
        called = []
        monkeypatch.setattr(page, "_ensure_sam", lambda: called.append(1))
        page._apply_mode(AnnotationMode.REGION_SAM)
        assert called == [1], "进入 SAM 区域模式应触发 _ensure_sam"
