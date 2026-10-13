"""批次 4 测试：L7/L8 几何 + E18 GT 类别 + L13 LabelMe 键 + L16 缓存验证。

（2026-10-06 三轮审查归档清偿——point_in_polygon 此前全仓零直接测试。）
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ============================== L7：point_in_polygon ============================== #


@pytest.mark.unit
def test_point_in_polygon_inside_outside_square():
    """正方形内部 True / 外部 False / 点数不足 False。"""
    from labeling.geometry import point_in_polygon

    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert point_in_polygon((5.0, 5.0), square) is True
    assert point_in_polygon((15.0, 5.0), square) is False
    assert point_in_polygon((5.0, 5.0), [(0.0, 0.0), (1.0, 1.0)]) is False


@pytest.mark.unit
def test_point_in_polygon_concave():
    """凹多边形：凹口内的点在外部。"""
    from labeling.geometry import point_in_polygon

    # L 形：凹口在右上
    l_shape = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
    assert point_in_polygon((2, 2), l_shape) is True   # 主体内
    assert point_in_polygon((8, 8), l_shape) is False  # 凹口（外）


@pytest.mark.unit
def test_point_in_polygon_horizontal_edge_no_crash():
    """L7：含水平边的多边形不抛异常、返回 bool（旧 1e-12 偏置被显式跳过替代）。"""
    from labeling.geometry import point_in_polygon

    # 顶/底均为水平边的三角形+矩形混合
    poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
    for y in (0.0, 2.5, 5.0):  # 含恰在水平边上的 y
        result = point_in_polygon((5.0, y), poly)
        assert isinstance(result, bool)


# ============================== L8/L15：close_polygon 共线校验 ============================== #


@pytest.mark.unit
def test_close_polygon_default_no_check():
    """L8 默认行为锚：共线三点默认不抛（静默闭合，旧行为）。"""
    from labeling.geometry import close_polygon

    collinear = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]
    result = close_polygon(collinear)
    assert len(result) == 4  # 闭合追加首点


@pytest.mark.unit
def test_close_polygon_collinear_raises_when_checked():
    """L8 核心：check_collinear=True + 全共线 → ValueError。"""
    from labeling.geometry import close_polygon

    collinear = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]
    with pytest.raises(ValueError, match="共线"):
        close_polygon(collinear, check_collinear=True)


@pytest.mark.unit
def test_close_polygon_valid_passes_check():
    """L8：正常多边形 check_collinear=True 照常闭合。"""
    from labeling.geometry import close_polygon

    tri = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    result = close_polygon(tri, check_collinear=True)
    assert len(result) == 4


@pytest.mark.unit
def test_close_polygon_already_closed_returns_as_is():
    """已闭合序列原样返回。"""
    from labeling.geometry import close_polygon

    closed = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0), (0.0, 0.0)]
    assert close_polygon(list(closed)) == tuple(closed)


# ============================== E18：extract_gt label_map ============================== #


@pytest.mark.unit
def test_extract_gt_with_label_map():
    """E18 核心：label_map 提供时标签为映射值（非全零）。"""
    from evaluation.eval_flow import extract_gt

    ann = {
        "shapes": [
            {"shape_type": "rectangle", "label": "crack",
             "points": [[1, 1], [5, 5]]},
            {"shape_type": "rectangle", "label": "pore",
             "points": [[2, 2], [6, 6]]},
        ]
    }
    boxes, labels = extract_gt(ann, label_map={"crack": 0, "pore": 1})
    assert boxes == [[1, 1, 5, 5], [2, 2, 6, 6]]
    assert labels == [0, 1], "类别必须按 map 真实化"


@pytest.mark.unit
def test_extract_gt_without_map_backward_compat():
    """E18 兼容锚：label_map=None 保持全零旧行为。"""
    from evaluation.eval_flow import extract_gt

    ann = {
        "shapes": [
            {"shape_type": "rectangle", "label": "crack",
             "points": [[1, 1], [5, 5]]},
        ]
    }
    boxes, labels = extract_gt(ann)
    assert labels == [0]


# ============================== L13：LabelMe 标准键 ============================== #


@pytest.mark.unit
def test_labelme_shape_roundtrip_preserves_standard_keys():
    """L13：写出 shape dict 含 description/fill_color/line_color 标准键。"""
    from labeling.base import AnnotationMode, Shape
    from labeling.io_labelme import shape_to_labelme

    shape = Shape(mode=AnnotationMode.RECTANGLE,
                  points=((1.0, 2.0), (30.0, 40.0)), label="defect")
    d = shape_to_labelme(shape)
    assert "description" in d and d["description"] == ""
    assert "fill_color" in d and d["fill_color"] is None
    assert "line_color" in d and d["line_color"] is None


# ============================== L16：set_image 缓存命中（既有实现补验证） ============================== #


@pytest.mark.unit
def test_sam_set_image_cache_hit_skips_embedding():
    """L16（重新定性为补测试）：同图二次 set_image → predictor.set_image
    只调一次（W21 is 快路径 + 哈希双卡缓存已实现，验证之）。"""
    import numpy as np

    from labeling.sam_adapter import SamAdapter

    adapter = SamAdapter(model_type="vit_b")

    class _FakePredictor:
        def __init__(self):
            self.calls = 0

        def set_image(self, image):
            self.calls += 1

    fake = _FakePredictor()
    adapter._predictor = fake
    img = np.zeros((8, 8, 3), dtype=np.uint8)

    adapter.set_image(img)
    adapter.set_image(img)  # 同对象 → is 快路径命中

    assert fake.calls == 1, "同图二次 set_image 必须命中缓存"


@pytest.mark.unit
def test_sam_load_bad_model_type_raises_runtime():
    """L10：未注册 model_type → RuntimeError（带可选项上下文），非裸 KeyError。"""
    from labeling.sam_adapter import SamAdapter

    adapter = SamAdapter(model_type="vit_zzz")
    pytest.importorskip("segment_anything")

    with pytest.raises(RuntimeError, match="model_type"):
        adapter.load("nonexistent.pth")


@pytest.mark.unit
def test_sam_set_image_rejects_2d_input():
    """L9：2 维灰度输入 → ValueError（HWC 3 通道契约显式拒绝）。"""
    import numpy as np

    from labeling.sam_adapter import SamAdapter

    adapter = SamAdapter(model_type="vit_b")

    class _FakePredictor:
        def set_image(self, image):
            pass

    adapter._predictor = _FakePredictor()

    with pytest.raises(ValueError, match="HWC"):
        adapter.set_image(np.zeros((8, 8), dtype=np.uint8))
