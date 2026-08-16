"""inference/sv_bridge 单元测试（W5-T1，依据 supervision 方法文章优化标注渲染）。

契约：DetectionResult → sv.Detections 字段映射（类别稳定排序）、类别配色框、
标签渲染、实例掩码叠加、语义图（无框 2D 掩码）半透明叠加、空结果不崩。
"""
from __future__ import annotations

import base64
import os

import pytest

np = pytest.importorskip("numpy")
sv = pytest.importorskip("supervision")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402
from inference.sv_bridge import render_result, result_to_detections  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _img(w=100, h=80):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _det_result(**kw):
    base = dict(task=TaskType.DET, boxes=None, scores=None, labels=None)
    base.update(kw)
    return DetectionResult(**base)


# ----------------------------- 桥接字段映射 ----------------------------- #
@pytest.mark.unit
def test_bridge_maps_boxes_scores_labels():
    r = _det_result(
        boxes=[[10, 10, 50, 60], [5, 5, 20, 25]],
        scores=(0.9, 0.4),
        labels=("scratch", "crack"),  # 故意乱序：class_id 须按类别名稳定排序
    )
    d = result_to_detections(r)
    assert d.xyxy.shape == (2, 4)
    np.testing.assert_allclose(d.confidence, [0.9, 0.4])
    assert list(d.class_id) == [1, 0]  # crack=0, scratch=1
    assert list(d.data["class_name"]) == ["scratch", "crack"]


@pytest.mark.unit
def test_bridge_empty_result():
    d = result_to_detections(_det_result())
    assert len(d) == 0
    assert d.mask is None


@pytest.mark.unit
def test_bridge_attaches_instance_masks_when_count_matches():
    masks = np.zeros((2, 80, 100), dtype=bool)
    masks[0, 0:5, 0:5] = True
    r = _det_result(
        boxes=[[10, 10, 50, 60], [60, 5, 95, 40]],
        scores=(0.9, 0.5),
        labels=("crack", "crack"),
        masks=masks,
    )
    d = result_to_detections(r)
    assert d.mask is not None
    assert d.mask.shape == (2, 80, 100)


@pytest.mark.unit
def test_bridge_skips_mask_when_count_mismatches():
    r = _det_result(
        boxes=[[10, 10, 50, 60]],
        labels=("crack",),
        masks=np.zeros((3, 80, 100), dtype=bool),
    )
    d = result_to_detections(r)
    assert d.mask is None  # 数量不一致不硬挂（sv 校验会炸）


# ----------------------------- 渲染 ----------------------------- #
@pytest.mark.unit
def test_render_per_class_colors():
    """两类目标 → 框线使用不同类别色（ColorLookup.CLASS）。

    取底边中点采样（标签画在框左上角上方，底边不受标签底色干扰）。
    """
    r = _det_result(
        boxes=[[20, 30, 150, 200], [180, 20, 300, 140]],
        scores=(0.9, 0.5),
        labels=("crack", "scratch"),
    )
    out = render_result(np.full((240, 320, 3), 60, np.uint8), r)
    assert out.shape == (240, 320, 3)

    def _border_color(y_mid: int, x: int) -> tuple:
        """扫底边带（±3px）取第一个非背景像素色。"""
        bg = (60, 60, 60)
        for y in range(y_mid - 3, y_mid + 4):
            px = tuple(int(v) for v in out[y, x])
            if px != bg:
                return px
        return bg

    c1 = _border_color(199, 85)   # 框1 (20,30,150,200) 底边中部
    c2 = _border_color(139, 240)  # 框2 (180,20,300,140) 底边中部
    assert c1 != (60, 60, 60) and c2 != (60, 60, 60), "框线未绘制"
    assert c1 != c2, f"两类框使用了相同颜色: {c1}"


@pytest.mark.unit
def test_render_instance_mask_overlay_visible():
    masks = np.zeros((1, 80, 100), dtype=bool)
    masks[0, 40:60, 40:60] = True  # 掩码区域在框内部空白处
    r = _det_result(
        boxes=[[10, 10, 90, 70]],
        scores=(0.9,),
        labels=("crack",),
        masks=masks,
    )
    out = render_result(_img(), r)
    assert tuple(int(v) for v in out[50, 50]) != (0, 0, 0), "掩码区域未叠加"


@pytest.mark.unit
def test_render_semantic_map_without_boxes():
    """语义分割结果（2D 掩码、无框）也要可见。"""
    masks = np.zeros((80, 100), dtype=bool)
    masks[20:40, 20:40] = True
    r = _det_result(task=TaskType.SSEG, masks=masks)
    out = render_result(_img(), r)
    assert tuple(int(v) for v in out[30, 30]) != (0, 0, 0), "语义图未叠加"
    assert tuple(int(v) for v in out[70, 70]) == (0, 0, 0), "掩码外区域被误改"


@pytest.mark.unit
def test_render_empty_result_returns_untouched():
    img = _img()
    out = render_result(img, _det_result())
    np.testing.assert_array_equal(out, img)


@pytest.mark.unit
def test_render_keypoints_drawn():
    r = _det_result(keypoints=[(30, 30), (60, 45)])
    out = render_result(_img(), r)
    assert tuple(int(v) for v in out[30, 30]) != (0, 0, 0), "关键点未绘制"


# ----------------------------- predict 页接线冒烟 ----------------------------- #
@pytest.mark.unit
def test_predict_show_result_smoke(tmp_path):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from gui.pages.predict.page import PredictPage

    p = tmp_path / "img.png"
    p.write_bytes(PNG_1PX)
    page = PredictPage()
    page._show_result(str(p), _det_result(boxes=[[0, 0, 1, 1]], labels=("d",)))
    assert not page.preview.pixmap().isNull()
