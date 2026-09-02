"""W62（FR-011）：裁剪标注切分工具。

对标 SKolpha「裁剪标注」（chm 4.5.1.3.9 / docs/skolpha-forensics-wave3.md §3.1）：
画一条裁剪线，把既有矩形/多边形一分为二，原形删除、新形生成（label/color 继承），
一次裁剪=一步撤销。规格锚（手算）：
- 矩形 (0,0)-(10,6) 被过 (-1,-1)-(9,7) 直线切：上边交 (0.25,0)、下边交 (7.75,6)
  → 中点 x=4.0 纵切。
- 同矩形被过 (-1,1)-(11,5) 直线切：左边交 (0,4/3)、右边交 (10,14/3) → 中点 y=3.0 横切。
"""
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsPathItem  # noqa: E402

from labeling import AnnotationMode, Shape  # noqa: E402
from labeling.canvas import AnnotationCanvas  # noqa: E402
from labeling.controller import AnnotationController  # noqa: E402
from labeling.crop import (  # noqa: E402
    split_polygon_by_line,
    split_rectangle_by_line,
)
from labeling.modes import make_labeler  # noqa: E402

RECT = ((0.0, 0.0), (10.0, 6.0))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ============================== 几何：矩形 ============================== #


@pytest.mark.unit
def test_rect_two_widths_vertical_cut():
    """过两宽（上/下边）→ 取交点中点 x=4.0 纵切为两个矩形。"""
    pieces = split_rectangle_by_line(RECT, (-1.0, -1.0), (9.0, 7.0))
    assert pieces is not None and len(pieces) == 2
    got = sorted(tuple(sorted(p)) for p in pieces)
    assert got == [
        ((0.0, 0.0), (4.0, 6.0)),
        ((4.0, 0.0), (10.0, 6.0)),
    ]


@pytest.mark.unit
def test_rect_two_heights_horizontal_cut():
    """过两高（左/右边）→ 取交点中点 y=3.0 横切。"""
    pieces = split_rectangle_by_line(RECT, (-1.0, 1.0), (11.0, 5.0))
    assert pieces is not None and len(pieces) == 2
    got = sorted(tuple(sorted(p)) for p in pieces)
    assert got == [
        ((0.0, 0.0), (10.0, 3.0)),
        ((0.0, 3.0), (10.0, 6.0)),
    ]


@pytest.mark.unit
def test_rect_adjacent_sides_no_cut():
    """过相邻两边（上+左）→ 不切。"""
    assert split_rectangle_by_line(RECT, (-1.0, 2.0), (3.0, -1.0)) is None


@pytest.mark.unit
def test_rect_collinear_edge_no_cut():
    """切线与边共线 → 不切。"""
    assert split_rectangle_by_line(RECT, (-3.0, 0.0), (13.0, 0.0)) is None


@pytest.mark.unit
def test_rect_diagonal_through_corners_no_cut():
    """切线恰过两对角点 → 角点不算严格交 → 不切。"""
    assert split_rectangle_by_line(RECT, (0.0, 0.0), (10.0, 6.0)) is None


@pytest.mark.unit
def test_rect_line_outside_no_cut():
    """切线在矩形外（平行下边外移）→ 不切。"""
    assert split_rectangle_by_line(RECT, (-5.0, 7.0), (15.0, 7.0)) is None


@pytest.mark.unit
def test_rect_degenerate_line_no_cut():
    """两点重合定义不了直线 → 不切。"""
    assert split_rectangle_by_line(RECT, (3.0, 3.0), (3.0, 3.0)) is None


# ============================== 几何：多边形 ============================== #

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
LSHAPE = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]
USHAPE = [
    (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (6.0, 10.0),
    (6.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0),
]


@pytest.mark.unit
def test_polygon_square_vertical_split():
    pieces = split_polygon_by_line(SQUARE, (5.0, -5.0), (5.0, 15.0))
    assert pieces is not None and len(pieces) == 2
    for piece in pieces:
        assert len(piece) >= 3
    got = sorted(tuple(sorted(piece)) for piece in pieces)
    assert got == [
        ((0.0, 0.0), (0.0, 10.0), (5.0, 0.0), (5.0, 10.0)),
        ((5.0, 0.0), (5.0, 10.0), (10.0, 0.0), (10.0, 10.0)),
    ]


@pytest.mark.unit
def test_polygon_lshape_two_crossings_split():
    """L 形两交点 → 两片（6 点 + 4 点）。"""
    pieces = split_polygon_by_line(LSHAPE, (5.0, -5.0), (5.0, 15.0))
    assert pieces is not None and len(pieces) == 2
    sizes = sorted(len(p) for p in pieces)
    assert sizes == [4, 6]
    for piece in pieces:
        xs = [p[0] for p in piece]
        assert max(xs) <= 10.0 + 1e-9 and min(xs) >= -1e-9


@pytest.mark.unit
def test_polygon_four_crossings_no_cut():
    """U 形被水平线穿 4 交点 → v1 诚实不支持（None）。"""
    assert split_polygon_by_line(USHAPE, (-1.0, 5.0), (11.0, 5.0)) is None


@pytest.mark.unit
def test_polygon_vertex_on_line_no_cut():
    """切线恰过顶点（side=0 歧义）→ v1 不切。"""
    assert split_polygon_by_line(SQUARE, (-1.0, 0.0), (1.0, 0.0)) is None


@pytest.mark.unit
def test_polygon_all_one_side_no_cut():
    assert split_polygon_by_line(SQUARE, (-1.0, -5.0), (11.0, -5.0)) is None


@pytest.mark.unit
def test_polygon_tolerates_closing_duplicate():
    """收尾重复点（闭合惯例）自动剥除后再切。"""
    closed = SQUARE + [SQUARE[0]]
    pieces = split_polygon_by_line(closed, (5.0, -5.0), (5.0, 15.0))
    assert pieces is not None and len(pieces) == 2


@pytest.mark.unit
def test_polygon_degenerate_inputs_no_cut():
    assert split_polygon_by_line([(0.0, 0.0), (5.0, 5.0)], (0.0, -1.0), (1.0, 1.0)) is None
    assert split_polygon_by_line(SQUARE, (3.0, 3.0), (3.0, 3.0)) is None


# ============================== 画布：单步撤销批量替换 ============================== #


@pytest.mark.unit
def test_replace_shapes_single_undo(qapp):
    canvas = AnnotationCanvas()
    canvas.add_shape(mode=AnnotationMode.RECTANGLE, label="a", points=[(0, 0), (10, 10)])
    original = canvas.shapes[0]
    canvas.add_shape(mode=AnnotationMode.RECTANGLE, label="b", points=[(20, 0), (30, 10)])

    new1 = Shape(mode=AnnotationMode.RECTANGLE, points=((0, 0), (5, 10)), label="a")
    new2 = Shape(mode=AnnotationMode.RECTANGLE, points=((5, 0), (10, 10)), label="a")
    canvas.replace_shapes({0: [new1, new2]})

    shapes = canvas.shapes
    assert len(shapes) == 3
    assert shapes[0] is new1 and shapes[1] is new2 and shapes[2].label == "b"

    canvas.undo()
    shapes = canvas.shapes
    assert len(shapes) == 2 and shapes[0] is original  # 一步恢复，对象身份不变


@pytest.mark.unit
def test_replace_shapes_empty_is_noop(qapp):
    canvas = AnnotationCanvas()
    canvas.add_shape(mode=AnnotationMode.RECTANGLE, label="a", points=[(0, 0), (10, 10)])
    canvas.replace_shapes({})
    assert len(canvas.shapes) == 1
    canvas.undo()  # 若 replace({}) 误入栈，此步会恢复 1 个形；正确=回空（撤销 add）
    assert len(canvas.shapes) == 0


# ============================== 控制器：CROP 两点交互 ============================== #


@pytest.mark.unit
def test_controller_crops_rectangle_into_two(qapp):
    canvas = AnnotationCanvas()
    canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, label="defect", points=[(0, 0), (10, 6)]
    )
    ctrl = AnnotationController(canvas, mode=AnnotationMode.POLYGON, label="defect")
    ctrl.set_mode(AnnotationMode.CROP)

    ctrl.handle_press((-1.0, -1.0))
    ctrl.handle_press((9.0, 7.0))

    shapes = canvas.shapes
    assert len(shapes) == 2
    assert all(s.mode is AnnotationMode.RECTANGLE and s.label == "defect" for s in shapes)
    got = sorted(tuple(sorted(s.points)) for s in shapes)
    assert got == [((0.0, 0.0), (4.0, 6.0)), ((4.0, 0.0), (10.0, 6.0))]


@pytest.mark.unit
def test_controller_crop_single_undo_restores_original(qapp):
    canvas = AnnotationCanvas()
    canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, label="defect", points=[(0, 0), (10, 6)]
    )
    original = canvas.shapes[0]
    ctrl = AnnotationController(canvas, mode=AnnotationMode.CROP, label="defect")
    ctrl.handle_press((-1.0, -1.0))
    ctrl.handle_press((9.0, 7.0))
    assert len(canvas.shapes) == 2

    canvas.undo()
    shapes = canvas.shapes
    assert len(shapes) == 1 and shapes[0] is original

    canvas.redo()
    assert len(canvas.shapes) == 2  # redo 可复切


@pytest.mark.unit
def test_controller_crop_skips_cut_line_shapes(qapp):
    """切割线形状不参与裁剪；未切中任何可切形状 → 画布无变化。"""
    canvas = AnnotationCanvas()
    canvas.add_shape(mode=AnnotationMode.CUT_LINE, label="l", points=[(0, 0), (10, 10)])
    canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, label="far", points=[(100, 100), (110, 110)]
    )
    before = canvas.shapes
    ctrl = AnnotationController(canvas, mode=AnnotationMode.CROP, label="defect")
    ctrl.handle_press((0.0, 10.0))  # 与切割线相交，但不切形状
    ctrl.handle_press((10.0, 0.0))
    assert canvas.shapes == before


@pytest.mark.unit
def test_controller_crop_splits_polygon(qapp):
    canvas = AnnotationCanvas()
    canvas.add_shape(
        mode=AnnotationMode.POLYGON, label="defect", points=list(LSHAPE)
    )
    ctrl = AnnotationController(canvas, mode=AnnotationMode.CROP, label="defect")
    ctrl.handle_press((5.0, -5.0))
    ctrl.handle_press((5.0, 15.0))
    shapes = canvas.shapes
    assert len(shapes) == 2
    assert all(
        s.mode is AnnotationMode.POLYGON and s.label == "defect" for s in shapes
    )


@pytest.mark.unit
def test_controller_crop_cancel_and_mode_switch_clear_pending(qapp):
    canvas = AnnotationCanvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.CROP, label="d")
    ctrl.handle_press((1.0, 1.0))
    assert ctrl._crop_start == (1.0, 1.0)
    ctrl.cancel()
    assert ctrl._crop_start is None

    ctrl.set_mode(AnnotationMode.CROP)
    ctrl.handle_press((2.0, 2.0))
    assert ctrl._crop_start == (2.0, 2.0)
    ctrl.set_mode(AnnotationMode.POLYGON)  # 离场清理
    assert ctrl._crop_start is None


@pytest.mark.unit
def test_controller_crop_preview_reuses_cut_line_render(qapp):
    canvas = AnnotationCanvas()
    canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, label="defect", points=[(0, 0), (10, 6)]
    )
    ctrl = AnnotationController(canvas, mode=AnnotationMode.CROP, label="defect")
    ctrl.handle_press((-1.0, -1.0))
    before = len(canvas.items())
    ctrl.handle_move((9.0, 7.0))
    after_items = canvas.items()
    assert len(after_items) == before + 1
    assert any(isinstance(i, QGraphicsPathItem) for i in after_items)


# ============================== 枚举/工厂/页面接线 ============================== #


@pytest.mark.unit
def test_enum_full_set_is_eight():
    assert len(list(AnnotationMode)) == 8
    assert AnnotationMode.CROP.value == "crop"


@pytest.mark.unit
def test_crop_is_tool_mode_not_manual():
    """CROP 同 EDIT：工具型——manual_modes 仍 4，无标注器。"""
    assert AnnotationMode.CROP not in AnnotationMode.manual_modes()
    assert make_labeler(AnnotationMode.CROP, "x") is None


@pytest.mark.unit
def test_page_mode_table_wires_crop():
    from gui.pages.label.page import _DRAW_MODES, _MODES

    assert (AnnotationMode.CROP, "裁剪", "X") in _MODES
    assert len(_MODES) == 8
    assert AnnotationMode.CROP in _DRAW_MODES
