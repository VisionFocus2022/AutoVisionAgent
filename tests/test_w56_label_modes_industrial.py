"""W56-A（FR-001/002）：切割线 + 操作标注工业形态。

对标 SKolpha cut_line_label / operation_label（形态名锚点 @0x3d52001-0x3d5205b，
交互语义为推断级——实机核对后按 PRD AC-010 回填修订）。

覆盖：Labeler 单元行为 / 工厂注册 / io_labelme 往返（linestrip 跨工具互操作）/
画布渲染（开放折线，防 QPolygonF 自动闭合回归）/ 控制器集成 / EDIT 边界 /
页面按钮接线与 transferType 联动入口。
"""
import os

import pytest

pytest.importorskip("PySide6")

# 必须在导入 PySide6 前设置 offscreen，避免无显示环境报错
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
)

from labeling import (  # noqa: E402
    AnnotationMode,
    Shape,
    load_labelme_shapes,
    save_labelme,
    shape_from_labelme,
    shape_to_labelme,
)
from labeling.canvas import AnnotationCanvas  # noqa: E402
from labeling.controller import AnnotationController  # noqa: E402
from labeling.modes import CutLineLabeler, OperationLabeler, make_labeler  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ============================== Labeler 单元 ============================== #


@pytest.mark.unit
def test_cut_line_commit_needs_two_points():
    """折线至少 2 点：单点提交被拒。"""
    labeler = CutLineLabeler("cut")
    labeler.on_press((10.0, 10.0))
    assert labeler.commit() is None

    labeler.on_press((30.0, 20.0))
    labeler.on_press((50.0, 10.0))
    shape = labeler.commit()
    assert shape is not None
    assert shape.mode is AnnotationMode.CUT_LINE
    assert len(shape.points) == 3
    assert shape.label == "cut"


@pytest.mark.unit
def test_cut_line_preview_includes_cursor():
    """预览 = 已落点 + 光标（进行中折线实时可见）。"""
    labeler = CutLineLabeler("cut")
    labeler.on_press((10.0, 10.0))
    labeler.on_press((30.0, 20.0))
    labeler.on_move((60.0, 40.0))
    preview = labeler.preview()
    assert preview is not None
    assert len(preview.points) == 3  # 2 已落点 + 光标


@pytest.mark.unit
def test_cut_line_points_not_closed():
    """与多边形的核心差异：提交点列不闭合（首尾不重合）。"""
    labeler = CutLineLabeler("cut")
    for pt in ((10.0, 10.0), (40.0, 15.0), (80.0, 60.0)):
        labeler.on_press(pt)
    shape = labeler.commit()
    assert shape.points[0] != shape.points[-1]


@pytest.mark.unit
def test_operation_drag_creates_shape():
    """操作标注：矩形拖拽 → OPERATION 形状；标签即操作名。"""
    labeler = OperationLabeler("打磨")
    labeler.on_press((10.0, 10.0))
    labeler.on_move((50.0, 60.0))
    shape = labeler.on_release((50.0, 60.0))
    assert shape is not None
    assert shape.mode is AnnotationMode.OPERATION
    assert shape.points == ((10.0, 10.0), (50.0, 60.0))
    assert shape.label == "打磨"


@pytest.mark.unit
def test_operation_small_drag_dropped():
    """误触保护沿用矩形语义：边长 < MIN_SIZE 的拖拽丢弃。"""
    labeler = OperationLabeler("op")
    labeler.on_press((10.0, 10.0))
    assert labeler.on_release((11.0, 10.5)) is None


# ============================== 工厂注册 ============================== #


@pytest.mark.unit
def test_make_labeler_industrial_modes():
    for mode, cls in (
        (AnnotationMode.CUT_LINE, CutLineLabeler),
        (AnnotationMode.OPERATION, OperationLabeler),
    ):
        labeler = make_labeler(mode, "x")
        assert isinstance(labeler, cls)
        assert labeler.mode is mode


@pytest.mark.unit
def test_manual_modes_include_industrial():
    """手动模式集合纳入两工业形态（test_sam_modes 遍历消费）。"""
    manual = set(AnnotationMode.manual_modes())
    assert {AnnotationMode.CUT_LINE, AnnotationMode.OPERATION} <= manual


# ============================== io_labelme 往返 ============================== #


@pytest.mark.unit
def test_cut_line_roundtrip(tmp_path):
    shape = Shape(
        mode=AnnotationMode.CUT_LINE,
        points=((10.0, 10.0), (40.0, 15.0), (80.0, 60.0)),
        label="cut1",
    )
    data = shape_to_labelme(shape)
    assert data["shape_type"] == "linestrip"
    assert data["mode"] == "cut_line"

    back = shape_from_labelme(data)
    assert back.mode is AnnotationMode.CUT_LINE
    assert back.points == ((10.0, 10.0), (40.0, 15.0), (80.0, 60.0))

    # 文件级往返
    path = tmp_path / "a.json"
    save_labelme(path, [shape], "img.png", 100, 120)
    loaded = load_labelme_shapes(path)
    assert len(loaded) == 1
    assert loaded[0].mode is AnnotationMode.CUT_LINE
    assert len(loaded[0].points) == 3  # 不闭合，点数原样


@pytest.mark.unit
def test_external_linestrip_without_mode_key_reads_as_cut_line():
    """外部 labelme 工具写的 linestrip（无 mode 自定义键）读为切割线（跨工具互操作）。"""
    data = {
        "label": "x",
        "points": [[1.0, 2.0], [3.0, 4.0]],
        "shape_type": "linestrip",
        "flags": {},
    }
    shape = shape_from_labelme(data)
    assert shape.mode is AnnotationMode.CUT_LINE


@pytest.mark.unit
def test_operation_roundtrip_and_plain_rectangle_compat():
    shape = Shape(
        mode=AnnotationMode.OPERATION,
        points=((10.0, 10.0), (50.0, 60.0)),
        label="搬运",
    )
    data = shape_to_labelme(shape)
    assert data["shape_type"] == "rectangle"
    assert data["mode"] == "operation"

    back = shape_from_labelme(data)
    assert back.mode is AnnotationMode.OPERATION
    assert back.label == "搬运"

    # 外部普通矩形（无 mode 键）不被误判为操作标注——向后兼容
    plain = {
        "label": "r",
        "points": [[0.0, 0.0], [9.0, 9.0]],
        "shape_type": "rectangle",
        "flags": {},
    }
    assert shape_from_labelme(plain).mode is AnnotationMode.RECTANGLE


# ============================== 画布渲染 ============================== #


@pytest.mark.unit
def test_canvas_cut_line_renders_open_path(qapp):
    """切割线渲染为 QPainterPath（开放折线）——防 QPolygonF 自动闭合回归。"""
    canvas = AnnotationCanvas()
    canvas.set_blank(200, 200)
    canvas.add_shape(
        mode=AnnotationMode.CUT_LINE, label="c",
        points=[(10.0, 10.0), (60.0, 20.0), (100.0, 80.0)],
    )
    paths = [it for it in canvas.items() if isinstance(it, QGraphicsPathItem)]
    assert paths, "切割线应渲染为 QGraphicsPathItem（开放折线）"


@pytest.mark.unit
def test_canvas_operation_renders_rect(qapp):
    canvas = AnnotationCanvas()
    canvas.set_blank(200, 200)
    canvas.add_shape(
        mode=AnnotationMode.OPERATION, label="op",
        points=[(10.0, 10.0), (60.0, 80.0)],
    )
    rects = [it for it in canvas.items() if isinstance(it, QGraphicsRectItem)]
    assert rects, "操作标注（矩形区域）应渲染为 QGraphicsRectItem"


# ============================== 控制器集成 ============================== #


@pytest.mark.unit
def test_controller_cut_line_flow(qapp):
    canvas = AnnotationCanvas()
    canvas.set_blank(200, 200)
    controller = AnnotationController(
        canvas, mode=AnnotationMode.CUT_LINE, label="cut"
    )
    for pt in ((10.0, 10.0), (40.0, 20.0), (70.0, 60.0)):
        controller.handle_press(pt)
    controller.handle_commit()
    shapes = canvas.shapes
    assert len(shapes) == 1
    assert shapes[0].mode is AnnotationMode.CUT_LINE
    assert shapes[0].label == "cut"


# ============================== EDIT 模式边界 ============================== #


@pytest.mark.unit
def test_edit_mode_rejects_cut_line_vertex_edit(qapp):
    """W55 顶点编辑仅多边形——切割线选中后 move_vertex 拒绝（边界留档）。"""
    canvas = AnnotationCanvas()
    canvas.set_blank(200, 200)
    canvas.add_shape(
        mode=AnnotationMode.CUT_LINE, label="c",
        points=[(10.0, 10.0), (60.0, 20.0), (100.0, 80.0)],
    )
    canvas.select_shape(0)
    assert canvas.move_vertex(0, (5.0, 5.0)) is False


# ============================== 页面接线 ============================== #


@pytest.fixture()
def label_page(qapp):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    yield page
    page.deleteLater()


@pytest.mark.unit
def test_industrial_mode_buttons_wired(label_page):
    for mode in (AnnotationMode.CUT_LINE, AnnotationMode.OPERATION):
        assert mode in label_page._mode_btns, f"{mode} 按钮缺失"

    label_page._apply_mode(AnnotationMode.CUT_LINE)
    assert label_page.controller.mode is AnnotationMode.CUT_LINE

    label_page._apply_mode(AnnotationMode.OPERATION)
    assert label_page.controller.mode is AnnotationMode.OPERATION


@pytest.mark.unit
def test_set_default_shape_mode_entry(label_page):
    """transferType 联动入口（W58-A 接线；W56 预留函数先行）。"""
    label_page.set_default_shape_mode(AnnotationMode.RECTANGLE)
    assert label_page.controller.mode is AnnotationMode.RECTANGLE

