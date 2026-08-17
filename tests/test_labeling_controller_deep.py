"""labeling/controller 深度补测（W10-T4：62% 洼地填平）。

覆盖：on_mouse_press/move/release 三事件分发（含右键提交、无 view /
无 labeler 早退）、_to_scene_point 真坐标转换（缩放 + 滚动条偏移下的
精确映射）、set_mode 的 labeler 复用/重建/非法模式降级、handle_commit
的 if 分支（AutoLabeler 队列）与 while 清空分支（逐个返回队列）、
cancel、attach_interactive 三态。全部离屏运行。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsView  # noqa: E402

from labeling import AnnotationMode, Shape  # noqa: E402
from labeling.canvas import AnnotationCanvas  # noqa: E402
from labeling.controller import AnnotationController  # noqa: E402
from labeling.modes import make_labeler  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _DuckEvent:
    """QMouseEvent 鸭子替身 — controller 只调用 button()/pos()。"""

    def __init__(self, button, pos: QPoint):
        self._button = button
        self._pos = pos

    def button(self):
        return self._button

    def pos(self) -> QPoint:
        return self._pos


def _canvas() -> AnnotationCanvas:
    c = AnnotationCanvas()
    c.set_blank(300, 300)
    return c


def _scaled_view(canvas: AnnotationCanvas, scale: float = 10.0) -> QGraphicsView:
    """缩放后的 view；场景 300x300 → 视口坐标 3000x3000 大于视口本身，
    滚动条归零后 mapToScene(x, y) == (x/scale, y/scale)，可精确断言。"""
    view = QGraphicsView(canvas)
    view.scale(scale, scale)
    view.horizontalScrollBar().setValue(0)
    view.verticalScrollBar().setValue(0)
    return view


# ============================== 属性 / 模式 ============================== #
@pytest.mark.unit
def test_label_property_default_and_update(qapp):
    ctrl = AnnotationController(_canvas())
    assert ctrl.label == "defect"  # 默认标签（line 65）
    ctrl.set_label("crack")
    assert ctrl.label == "crack"
    assert ctrl._labeler.label == "crack"  # 同步到标注器


@pytest.mark.unit
def test_set_mode_same_mode_reuses_labeler(qapp):
    ctrl = AnnotationController(_canvas(), mode=AnnotationMode.RECTANGLE)
    lab1 = ctrl._labeler
    ctrl.set_mode(AnnotationMode.RECTANGLE)  # 同模式 → 复用，不重建
    assert ctrl._labeler is lab1
    assert ctrl.mode is AnnotationMode.RECTANGLE


@pytest.mark.unit
def test_set_mode_different_mode_rebuilds_labeler(qapp):
    ctrl = AnnotationController(_canvas(), mode=AnnotationMode.RECTANGLE, label="d")
    lab1 = ctrl._labeler
    ctrl.set_mode(AnnotationMode.POLYGON)
    assert ctrl._labeler is not lab1  # 重建
    assert ctrl._labeler.label == "d"  # 保留标签


@pytest.mark.unit
def test_invalid_mode_degrades_to_none_labeler(qapp):
    """非法模式 → make_labeler 抛 ValueError → labeler=None（lines 73-75）。"""
    ctrl = AnnotationController(_canvas(), mode="bogus")
    assert ctrl._labeler is None
    # 同为非法模式且 labeler=None → 仍会重试重建（再次降级）
    ctrl.set_mode("bogus")
    assert ctrl._labeler is None
    # 恢复到合法模式后 labeler 可用
    ctrl.set_mode(AnnotationMode.POLYGON)
    assert ctrl._labeler is not None


# ============================== install / 坐标转换 ============================== #
@pytest.mark.unit
def test_install_sets_view_and_mouse_tracking(qapp):
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.POLYGON)
    view = QGraphicsView(canvas)
    assert not view.hasMouseTracking()
    ctrl.install(view)
    assert ctrl._view is view
    assert view.hasMouseTracking()  # install 必开鼠标跟踪


@pytest.mark.unit
def test_to_scene_point_applies_view_transform(qapp):
    """view 坐标 → scene 坐标必须真实经过 view 变换与滚动条偏移。"""
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.RECTANGLE)
    view = _scaled_view(canvas, scale=10.0)
    ev = _DuckEvent(Qt.LeftButton, QPoint(30, 90))
    assert ctrl._to_scene_point(view, ev) == (3.0, 9.0)  # 30/10, 90/10

    view.horizontalScrollBar().setValue(100)
    view.verticalScrollBar().setValue(200)
    # 滚动后：(view + scroll) / scale
    assert ctrl._to_scene_point(view, ev) == (13.0, 29.0)


# ============================== 鼠标三事件分发 ============================== #
@pytest.mark.unit
def test_mouse_events_without_view_are_noop(qapp):
    """未 install（_view=None）→ 三事件全部早退，不产出形状。"""
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.RECTANGLE)
    ev = _DuckEvent(Qt.LeftButton, QPoint(10, 20))
    ctrl.on_mouse_press(ev)
    ctrl.on_mouse_move(ev)
    ctrl.on_mouse_release(ev)
    assert canvas.shapes == []


@pytest.mark.unit
def test_mouse_events_with_none_labeler_are_noop(qapp):
    """labeler=None（非法模式降级）→ 三事件全部早退。"""
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode="bogus")
    ctrl.install(_scaled_view(canvas))
    assert ctrl._view is not None
    ev = _DuckEvent(Qt.LeftButton, QPoint(10, 20))
    ctrl.on_mouse_press(ev)
    ctrl.on_mouse_move(ev)
    ctrl.on_mouse_release(ev)
    assert canvas.shapes == []


@pytest.mark.unit
def test_on_mouse_press_move_release_rectangle_full_cycle(qapp):
    """矩形：press/move/release 经坐标转换后完成形状提交。"""
    canvas = _canvas()
    ctrl = AnnotationController(
        canvas, mode=AnnotationMode.RECTANGLE, label="r"
    )
    ctrl.install(_scaled_view(canvas, scale=10.0))

    ctrl.on_mouse_press(_DuckEvent(Qt.LeftButton, QPoint(100, 100)))
    assert canvas.shapes == []  # press 只落点不提交
    ctrl.on_mouse_move(_DuckEvent(Qt.LeftButton, QPoint(400, 200)))
    assert canvas.shapes == []  # move 只预览
    ctrl.on_mouse_release(_DuckEvent(Qt.LeftButton, QPoint(400, 200)))

    assert len(canvas.shapes) == 1
    sh = canvas.shapes[0]
    assert sh.mode is AnnotationMode.RECTANGLE
    assert sh.label == "r"
    # view(100,100)→scene(10,10)；view(400,200)→scene(40,20)
    assert sh.points == ((10.0, 10.0), (40.0, 20.0))


@pytest.mark.unit
def test_on_mouse_press_right_button_triggers_commit(qapp):
    """多边形：三次左键落点后右键按下 → handle_commit 闭合提交。"""
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.POLYGON, label="poly")
    ctrl.install(_scaled_view(canvas, scale=10.0))

    ctrl.on_mouse_move(_DuckEvent(Qt.LeftButton, QPoint(5, 5)))  # 未落点先移动
    for vp in ((100, 100), (500, 100), (500, 500)):
        ctrl.on_mouse_press(_DuckEvent(Qt.LeftButton, QPoint(*vp)))
    assert canvas.shapes == []
    ctrl.on_mouse_press(_DuckEvent(Qt.RightButton, QPoint(0, 0)))  # 右键提交

    assert len(canvas.shapes) == 1
    sh = canvas.shapes[0]
    assert sh.label == "poly"
    assert sh.points[0] == sh.points[-1]  # 闭合
    assert (10.0, 10.0) == sh.points[0]  # 首点来自真实坐标转换


# ============================== 便捷 API 早退 ============================== #
@pytest.mark.unit
def test_handle_api_with_none_labeler_noop(qapp):
    ctrl = AnnotationController(_canvas(), mode="bogus")
    ctrl.handle_press((1.0, 1.0))  # line 143
    ctrl.handle_move((2.0, 2.0))  # line 153
    ctrl.handle_release((3.0, 3.0))  # line 163
    ctrl.handle_commit()  # line 176
    assert ctrl._canvas.shapes == []


# ============================== handle_commit ============================== #
@pytest.mark.unit
def test_handle_commit_auto_labeler_queue_if_branch(qapp):
    """AUTO 模式：commit 逐个返回队列形状（if 分支），队列空后再 commit
    走 while 清空分支并立即 break。"""
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.AUTO, label="ai")
    ctrl._labeler.set_detector(
        lambda img: [
            Shape(AnnotationMode.RECTANGLE, ((0, 0), (5, 5)), label="ai"),
            Shape(AnnotationMode.KEYPOINT, ((1, 1),), label="ai"),
        ]
    )
    ctrl._labeler.set_image(object())
    ctrl.handle_press((1.0, 1.0))  # on_press 触发 run → 队列 2 个
    assert ctrl._labeler.pending_count == 2

    ctrl.handle_commit()  # if 分支提交第 1 个
    ctrl.handle_commit()  # if 分支提交第 2 个
    ctrl.handle_commit()  # 首个 commit None → while → None → break
    assert ctrl._labeler.pending_count == 0
    assert len(canvas.shapes) == 2
    assert [s.label for s in canvas.shapes] == ["ai", "ai"]


class _ScriptedLabeler:
    """脚本化标注器：按预设序列返回 commit() 结果，其余方法无操作。"""

    mode = AnnotationMode.POLYGON

    def __init__(self, commit_results):
        self._results = list(commit_results)
        self.label = "script"

    def on_press(self, pt):
        pass

    def on_move(self, pt):
        pass

    def on_release(self, pt):
        return None

    def preview(self):
        return None

    def commit(self):
        return self._results.pop(0) if self._results else None

    def reset(self):
        pass


@pytest.mark.unit
def test_handle_commit_while_loop_drains_multiple_shapes(qapp):
    """首 commit 返回 None 后 while 循环逐个取完队列再 break（lines 182-186）。"""
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.POLYGON, label="d")
    ctrl._labeler = _ScriptedLabeler(
        [
            None,  # 首个 commit None → 进入 while
            Shape(AnnotationMode.RECTANGLE, ((0, 0), (1, 1)), label="q1"),
            Shape(AnnotationMode.KEYPOINT, ((2, 2),), label="q2"),
            None,  # 队列耗尽 → break
        ]
    )
    ctrl.handle_commit()
    assert len(canvas.shapes) == 2
    assert canvas.shapes[0].label == "q1"
    assert canvas.shapes[1].label == "q2"
    assert canvas.shapes[1].mode is AnnotationMode.KEYPOINT


# ============================== cancel ============================== #
@pytest.mark.unit
def test_cancel_resets_labeler_and_keeps_canvas(qapp):
    canvas = _canvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.POLYGON, label="d")
    ctrl.handle_press((10.0, 10.0))
    ctrl.handle_press((50.0, 10.0))
    assert ctrl._labeler.points != ()

    ctrl.cancel()
    assert ctrl._labeler.points == ()  # 标注器被 reset（lines 190-191）
    assert canvas.shapes == []
    ctrl.handle_commit()  # 取消后提交无产出
    assert canvas.shapes == []


# ============================== attach_interactive ============================== #
@pytest.mark.unit
def test_attach_interactive_success_injects_adapter_and_image(qapp):
    canvas = _canvas()
    ctrl = AnnotationController(
        canvas, mode=AnnotationMode.INTERACTIVE, label="sam"
    )
    adapter = object()
    image = object()
    assert ctrl.attach_interactive(adapter, image=image) is True
    assert ctrl._labeler._adapter is adapter
    assert ctrl._labeler._image is image


@pytest.mark.unit
def test_attach_interactive_rejects_non_interactive_mode(qapp):
    ctrl = AnnotationController(_canvas(), mode=AnnotationMode.POLYGON, label="d")
    assert ctrl.attach_interactive(object()) is False


@pytest.mark.unit
def test_attach_interactive_rejects_labeler_without_set_adapter(qapp):
    """INTERACTIVE 模式但标注器不支持注入（无 set_adapter）→ False（line 205）。"""
    ctrl = AnnotationController(
        _canvas(), mode=AnnotationMode.INTERACTIVE, label="sam"
    )
    ctrl._labeler = make_labeler(AnnotationMode.POLYGON, "d")  # 无 set_adapter
    assert ctrl.attach_interactive(object()) is False
