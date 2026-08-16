"""labeling 子系统单元测试（FR-C1/C4/C5）。

覆盖：纯几何工具、4 手动模式 to_shape、LabelMe JSON 往返、画布撤销/重做、
控制器事件分发→形状提交。Qt 相关用例在 offscreen 模式下运行。
"""
import os

# 必须在导入 PySide6 前设置 offscreen，避免无显示环境报错
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")  # 无 PySide6 则跳过本模块

import json
import tempfile

from PySide6.QtWidgets import QApplication  # noqa: E402

from labeling import (  # noqa: E402
    AnnotationMode,
    Shape,
    labelme_to_shapes,
    load_labelme_shapes,
    save_labelme,
    shape_from_labelme,
    shape_to_labelme,
    shapes_to_labelme,
)
from labeling.canvas import AnnotationCanvas  # noqa: E402
from labeling.controller import AnnotationController  # noqa: E402
from labeling.geometry import (  # noqa: E402
    close_polygon,
    is_closed,
    normalize_rectangle,
    polygon_area,
    polygon_centroid,
    rectangle_size,
    simplify_polyline,
)
from labeling.modes import make_labeler  # noqa: E402
from core.exceptions import AnnotationIOError, InvalidShapeError  # noqa: E402


# Qt 应用级会话只允许一个 QApplication 实例
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ============================== 几何工具 ============================== #
@pytest.mark.unit
def test_normalize_rectangle_any_order():
    assert normalize_rectangle((110, 60), (10, 10)) == ((10, 10), (110, 60))
    assert normalize_rectangle((10, 10), (110, 60)) == ((10, 10), (110, 60))


@pytest.mark.unit
def test_rectangle_size():
    assert rectangle_size((0, 0), (100, 50)) == (100, 50)


@pytest.mark.unit
def test_polygon_area_square():
    pts = ((0, 0), (50, 0), (50, 50), (0, 50))
    assert polygon_area(pts) == pytest.approx(2500.0)
    assert polygon_area(((0, 0), (1, 1))) == 0.0  # 点数不足


@pytest.mark.unit
def test_polygon_centroid_square():
    cx, cy = polygon_centroid(((0, 0), (100, 0), (100, 100), (0, 100)))
    assert (cx, cy) == pytest.approx((50, 50))


@pytest.mark.unit
def test_close_polygon_appends_first_point():
    pts = ((0, 0), (10, 0), (10, 10))
    closed = close_polygon(pts)
    assert is_closed(closed)
    assert closed[0] == closed[-1]


@pytest.mark.unit
def test_simplify_polyline_straight_line_collapses():
    # 共线点应塌缩为两端点
    pts = [(float(x), 0.0) for x in range(0, 101, 5)]
    out = simplify_polyline(pts, epsilon=1.0)
    assert len(out) == 2
    assert out[0] == pts[0] and out[-1] == pts[-1]


@pytest.mark.unit
def test_simplify_polyline_keeps_big_deviation():
    # 显著偏离的点必须保留
    pts = [(0.0, 0.0), (50.0, 50.0), (100.0, 0.0)]
    out = simplify_polyline(pts, epsilon=2.0)
    assert (50.0, 50.0) in out


# ============================== 标注模式 ============================== #
@pytest.mark.unit
def test_rectangle_mode_normalizes_and_drops_tiny():
    lab = make_labeler(AnnotationMode.RECTANGLE, "d")
    lab.on_press((10, 10))
    lab.on_move((110, 60))
    sh = lab.on_release((110, 60))
    assert sh is not None
    assert sh.mode is AnnotationMode.RECTANGLE
    assert sh.points == ((10, 10), (110, 60))

    # 误触小矩形被丢弃
    tiny = make_labeler(AnnotationMode.RECTANGLE, "d")
    tiny.on_press((0, 0))
    assert tiny.on_release((0.5, 0.5)) is None


@pytest.mark.unit
def test_keypoint_mode_single_point():
    lab = make_labeler(AnnotationMode.KEYPOINT, "kp")
    lab.on_press((25, 25))
    sh = lab.on_release((25, 25))
    assert sh is not None and sh.points == ((25, 25),)


@pytest.mark.unit
def test_polygon_mode_commit_closes():
    lab = make_labeler(AnnotationMode.POLYGON, "crack")
    for pt in [(0, 0), (50, 0), (50, 50), (0, 50)]:
        lab.on_press((float(pt[0]), float(pt[1])))
    sh = lab.commit()
    assert sh is not None
    assert sh.points[0] == sh.points[-1]  # 闭合
    # commit 后状态清空
    assert lab.points == ()


@pytest.mark.unit
def test_polygon_mode_snap_to_first_point():
    lab = make_labeler(AnnotationMode.POLYGON, "crack", close_threshold=10)
    for pt in [(0, 0), (50, 0), (50, 50)]:
        lab.on_press((float(pt[0]), float(pt[1])))
    lab.on_press((1, 1))  # 靠近首点 → 视为闭合意图
    sh = lab.commit()
    assert sh is not None and len(sh.points) >= 4


@pytest.mark.unit
def test_brush_mode_simplifies_stroke():
    lab = make_labeler(
        AnnotationMode.BRUSH, "mask", sample_distance=2, simplify_epsilon=3
    )
    # 真实画笔：沿方形闭合轨迹高密度采样（共线直线会被丢弃，故用闭合环）
    corners = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]
    loop = corners + [corners[0]]
    raw = []
    for a, b in zip(loop, loop[1:]):
        for i in range(10):
            raw.append((a[0] + (b[0] - a[0]) * i / 10,
                        a[1] + (b[1] - a[1]) * i / 10))
    lab.on_press(raw[0])
    for q in raw[1:]:
        lab.on_move(q)
    sh = lab.on_release(raw[-1])
    assert sh is not None
    assert sh.mode is AnnotationMode.BRUSH
    # 高密度采样应被简化为少量角点（≥3 且远少于原始采样）
    assert len(sh.points) >= 3
    assert len(sh.points) < len(raw)


@pytest.mark.unit
def test_brush_mode_degenerate_line_dropped():
    # 完全共线的直线笔触 → 简化为 2 点 < 3 → 丢弃（不构成区域）
    lab = make_labeler(
        AnnotationMode.BRUSH, "mask", sample_distance=2, simplify_epsilon=3
    )
    raw = [(float(x), 10.0) for x in range(0, 100, 2)]
    lab.on_press(raw[0])
    for q in raw[1:]:
        lab.on_move(q)
    assert lab.on_release(raw[-1]) is None


@pytest.mark.unit
def test_polygon_preview_rubber_band():
    lab = make_labeler(AnnotationMode.POLYGON, "d")
    lab.on_press((0, 0))
    lab.on_press((50, 0))
    lab.on_move((50, 50))
    prev = lab.preview()
    assert prev is not None
    assert (50, 50) == prev.points[-1]  # 末端为光标


@pytest.mark.unit
def test_factory_supports_m2_modes():
    """AUTO/INTERACTIVE 模式在 M2 (T-M2-03 SAM) 已实装。"""
    from labeling.modes.auto import AutoLabeler
    from labeling.modes.interactive import InteractiveLabeler
    auto = make_labeler(AnnotationMode.AUTO, "d")
    assert isinstance(auto, AutoLabeler)
    inter = make_labeler(AnnotationMode.INTERACTIVE, "d")
    assert isinstance(inter, InteractiveLabeler)


# ============================== LabelMe IO ============================== #
@pytest.mark.unit
def test_shape_to_labelme_shape_types():
    rect = Shape(AnnotationMode.RECTANGLE, ((10, 10), (110, 60)), label="r")
    poly = Shape(AnnotationMode.POLYGON, ((0, 0), (1, 0), (1, 1)), label="p")
    kp = Shape(AnnotationMode.KEYPOINT, ((5, 5),), label="k")
    brush = Shape(AnnotationMode.BRUSH, ((0, 0), (5, 1), (10, 0), (10, 10)), label="b")
    assert shape_to_labelme(rect)["shape_type"] == "rectangle"
    assert shape_to_labelme(poly)["shape_type"] == "polygon"
    assert shape_to_labelme(kp)["shape_type"] == "point"
    assert shape_to_labelme(brush)["shape_type"] == "polygon"


@pytest.mark.unit
def test_labelme_round_trip_preserves_mode_label_points():
    shapes = [
        Shape(AnnotationMode.RECTANGLE, ((10, 10), (110, 60)), label="crack"),
        Shape(
            AnnotationMode.POLYGON,
            ((0, 0), (50, 0), (50, 50)),
            label="scratch",
            group_id=3,
        ),
        Shape(AnnotationMode.KEYPOINT, ((25, 25),), label="kp"),
        Shape(
            AnnotationMode.BRUSH,
            ((5, 5), (20, 6), (40, 5), (40, 20)),
            label="mask",
        ),
    ]
    doc = shapes_to_labelme(shapes, "demo.jpg", 480, 640)
    back = labelme_to_shapes(doc)
    assert [s.mode for s in back] == [s.mode for s in shapes]  # 含 brush 身份
    assert [s.label for s in back] == [s.label for s in shapes]
    assert back[0].points == shapes[0].points
    assert back[2].points == shapes[2].points
    assert back[1].group_id == 3


@pytest.mark.unit
def test_labelme_save_load_file_and_errors(tmp_path):
    shapes = [
        Shape(AnnotationMode.RECTANGLE, ((1, 1), (9, 9)), label="d"),
    ]
    fp = tmp_path / "demo.json"
    save_labelme(str(fp), shapes, "demo.jpg", 100, 100)
    data = json.loads(fp.read_text(encoding="utf-8"))
    assert data["imageWidth"] == 100 and len(data["shapes"]) == 1
    loaded = load_labelme_shapes(str(fp))
    assert loaded[0].mode is AnnotationMode.RECTANGLE

    # 缺失文件 → AnnotationIOError
    with pytest.raises(AnnotationIOError):
        load_labelme_shapes(str(tmp_path / "nope.json"))


@pytest.mark.unit
def test_shape_to_labelme_empty_points_raises():
    with pytest.raises(InvalidShapeError):
        shape_to_labelme(Shape(AnnotationMode.POLYGON, (), label="x"))


@pytest.mark.unit
def test_shape_from_labelme_infers_mode_without_custom_key():
    # 无 "mode" 自定义键时按 shape_type 推断
    d = {
        "label": "r",
        "points": [[1, 1], [9, 9]],
        "group_id": None,
        "shape_type": "rectangle",
        "flags": {},
    }
    sh = shape_from_labelme(d)
    assert sh.mode is AnnotationMode.RECTANGLE


# ============================== 画布撤销/重做 ============================== #
@pytest.mark.unit
def test_canvas_undo_redo(qapp):
    c = AnnotationCanvas()
    c.set_blank(200, 200)
    s1 = Shape(AnnotationMode.RECTANGLE, ((1, 1), (2, 2)), label="a")
    s2 = Shape(AnnotationMode.KEYPOINT, ((5, 5),), label="b")

    c.add_shape(s1)
    c.add_shape(s2)
    assert len(c.shapes) == 2
    assert c.can_undo() and not c.can_redo()

    assert c.undo()
    assert len(c.shapes) == 1 and c.shapes[0] is s1
    assert c.can_redo()

    assert c.redo()
    assert len(c.shapes) == 2

    # 撤销到底
    assert c.undo() and c.undo()
    assert len(c.shapes) == 0
    assert not c.undo()  # 空栈

    # 新变更应清空 redo 栈
    c.redo()
    c.add_shape(s1)
    assert not c.can_redo()


@pytest.mark.unit
def test_canvas_clear_shapes_undoable(qapp):
    c = AnnotationCanvas()
    c.add_shape(Shape(AnnotationMode.RECTANGLE, ((1, 1), (2, 2)), label="a"))
    c.clear_shapes()
    assert len(c.shapes) == 0
    assert c.undo()
    assert len(c.shapes) == 1


@pytest.mark.unit
def test_canvas_replace_all_undoable(qapp):
    c = AnnotationCanvas()
    c.add_shape(Shape(AnnotationMode.RECTANGLE, ((1, 1), (2, 2)), label="a"))
    c.replace_all(
        (Shape(AnnotationMode.KEYPOINT, ((9, 9),), label="b"),)
    )
    assert len(c.shapes) == 1 and c.shapes[0].mode is AnnotationMode.KEYPOINT
    assert c.undo()
    assert c.shapes[0].mode is AnnotationMode.RECTANGLE


# ============================== 控制器 e2e ============================== #
@pytest.mark.unit
def test_controller_rectangle_then_keypoint(qapp):
    c = AnnotationCanvas()
    c.set_blank(200, 200)
    ctrl = AnnotationController(c, mode=AnnotationMode.RECTANGLE, label="crack")
    ctrl.handle_press((10, 10))
    ctrl.handle_move((100, 60))
    ctrl.handle_release((100, 60))
    assert len(c.shapes) == 1
    assert c.shapes[0].mode is AnnotationMode.RECTANGLE

    ctrl.set_mode(AnnotationMode.KEYPOINT)
    ctrl.set_label("kp")
    ctrl.handle_press((30, 30))
    ctrl.handle_release((30, 30))
    assert len(c.shapes) == 2
    assert c.shapes[1].label == "kp"


@pytest.mark.unit
def test_controller_polygon_commit(qapp):
    c = AnnotationCanvas()
    c.set_blank(200, 200)
    ctrl = AnnotationController(c, mode=AnnotationMode.POLYGON, label="crack")
    for pt in [(10, 10), (80, 10), (80, 80), (10, 80)]:
        ctrl.handle_press((float(pt[0]), float(pt[1])))
    ctrl.handle_commit()
    assert len(c.shapes) == 1
    assert c.shapes[0].points[0] == c.shapes[0].points[-1]  # 闭合


@pytest.mark.unit
def test_controller_undo_clears_active_drawing(qapp):
    c = AnnotationCanvas()
    c.set_blank(200, 200)
    ctrl = AnnotationController(c, mode=AnnotationMode.POLYGON, label="d")
    ctrl.handle_press((10, 10))
    ctrl.handle_press((50, 10))
    # 切换模式应丢弃进行中绘制，不产出形状
    ctrl.set_mode(AnnotationMode.RECTANGLE)
    assert len(c.shapes) == 0
