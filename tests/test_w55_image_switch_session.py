"""W55·v7 P1-1：换图硬清空画布会话。

三断言面：
① canvas.reset_session 清形状并清空撤销/重做栈（跨图边界 Ctrl+Z 不得
   复活上一图形状——clear_shapes 留撤销快照，正门清了后门还开）；
② 页级 _load_by_index 换图后画布形状为空、撤销不可用；
③ Ctrl+C → 换图 → Ctrl+V 显式携带通道仍可用（清空只关「意外携带」）。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from labeling import AnnotationMode  # noqa: E402
from labeling.canvas import AnnotationCanvas  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


@pytest.fixture
def label_page(qapp):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    msgs: list[tuple[str, str]] = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


@pytest.fixture
def folder2(tmp_path):
    d = tmp_path / "imgs"
    d.mkdir()
    _png(d / "a.png")
    _png(d / "b.png")
    return d


def _open_folder(label_page, monkeypatch, folder):
    from gui.pages.label import page as label_mod

    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(folder))
    label_page.open_folder()
    label_page._thumb_pool.waitForDone(3000)


# ============================== ① canvas.reset_session ============================== #


@pytest.mark.unit
def test_reset_session_clears_shapes_and_both_stacks(qapp):
    canvas = AnnotationCanvas()
    canvas.add_shape(mode=AnnotationMode.RECTANGLE, points=[(1, 1), (10, 10)])
    canvas.add_shape(mode=AnnotationMode.POLYGON, points=[(0, 0), (5, 0), (5, 5)])
    assert len(canvas.shapes) == 2
    assert canvas.can_undo() is True

    canvas.reset_session()

    assert canvas.shapes == []
    assert canvas.can_undo() is False
    assert canvas.can_redo() is False


@pytest.mark.unit
def test_reset_session_is_hard_no_undo_resurrection(qapp):
    """与 clear_shapes 的区别：清空后 undo 不得恢复（跨图边界）。"""
    canvas = AnnotationCanvas()
    canvas.add_shape(mode=AnnotationMode.RECTANGLE, points=[(1, 1), (10, 10)])

    canvas.reset_session()
    assert canvas.undo() is False  # 撤销后门关闭
    assert canvas.shapes == []


@pytest.mark.unit
def test_reset_session_idempotent_on_empty(qapp):
    canvas = AnnotationCanvas()
    canvas.reset_session()
    assert canvas.shapes == []
    assert canvas.can_undo() is False


# ============================== ② 页级换图清空 ============================== #


@pytest.mark.unit
def test_image_switch_clears_shapes_and_undo(label_page, monkeypatch, folder2):
    _open_folder(label_page, monkeypatch, folder2)
    label_page.canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, points=[(1, 1), (10, 10)]
    )
    assert len(label_page.canvas.shapes) == 1

    label_page.next_image()

    assert label_page.canvas.shapes == []
    assert label_page.canvas.can_undo() is False


# ============================== ③ 显式携带通道不破坏 ============================== #


@pytest.mark.unit
def test_copy_switch_paste_channel_survives(label_page, monkeypatch, folder2):
    _open_folder(label_page, monkeypatch, folder2)
    label_page.canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, points=[(1, 1), (10, 10)]
    )
    label_page.shape_list.setCurrentRow(0)
    label_page._copy_shapes()
    assert label_page._clipboard, "复制应填充页级剪贴板"

    label_page.next_image()
    assert label_page.canvas.shapes == []  # 换图清空生效

    label_page._paste_shapes()
    assert len(label_page.canvas.shapes) == 1  # 显式携带仍可用


# ============================== W55·v7 P1-2：换图 SAM 会话同步 ============================== #


class FakeSamAdapter:
    """记录 set_image 调用的已加载假适配器（预热/注入链专用）。"""

    def __init__(self):
        self.loaded = True
        self.images: list = []

    def set_image(self, img):
        self.images.append(img)

    def build_amg_detector(self, label="defect"):
        return lambda image: []


@pytest.fixture
def fake_threads(monkeypatch):
    import threading

    class _FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target, self._args, self._kwargs = target, args, kwargs or {}

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(threading, "Thread", _FakeThread)


@pytest.fixture
def marker_imread(monkeypatch):
    """imread 按路径返回可判别标记（str），使换图前后帧可断言。"""
    import core.image_io as imgio

    monkeypatch.setattr(
        imgio, "imread_unicode", lambda p: f"IMG::{os.path.basename(p)}"
    )


_SAM_MODES = [
    AnnotationMode.INTERACTIVE,
    AnnotationMode.REGION_SAM,
    AnnotationMode.AUTO,
]


@pytest.mark.unit
@pytest.mark.parametrize("mode", _SAM_MODES)
def test_switch_image_syncs_sam_session_all_modes(
    label_page, monkeypatch, folder2, fake_threads, marker_imread, mode
):
    """换图后 SAM 各模式的 labeler 都持新帧（v7 P1-2 主断言）。"""
    _open_folder(label_page, monkeypatch, folder2)
    adapter = FakeSamAdapter()
    label_page._sam_adapter = adapter

    label_page._apply_mode(mode)
    label_page._thumb_pool.waitForDone(3000)
    label_page._load_by_index(0)
    label_page._apply_mode(mode)  # 触发 _ensure_sam → 预热注入
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    labeler = label_page.controller._labeler
    assert labeler is not None
    assert labeler._image == "IMG::a.png", "首图应完成注入"

    label_page.next_image()
    QApplication.processEvents()

    assert labeler._image == "IMG::b.png", (
        "换图后 labeler 应持新帧——旧帧残留即静默错标通道（v7 P1-2）"
    )


@pytest.mark.unit
def test_switch_invalidates_image_before_warm_completes(
    label_page, monkeypatch, folder2
):
    """换图瞬间（预热未完成窗口）labeler 帧引用必须已失效为 None。"""
    _open_folder(label_page, monkeypatch, folder2)
    adapter = FakeSamAdapter()
    label_page._sam_adapter = adapter
    label_page._apply_mode(AnnotationMode.INTERACTIVE)
    labeler = label_page.controller._labeler
    labeler.set_image("IMG::stale")

    rewarm_calls: list[int] = []
    monkeypatch.setattr(label_page, "_warm_sam", lambda: rewarm_calls.append(1))

    label_page.next_image()

    assert labeler._image is None, "换图后、新帧预热完成前，预测必须 no-op"
    assert rewarm_calls, "换图应触发 re-warm"


@pytest.mark.unit
def test_stale_warm_result_not_attached(
    label_page, monkeypatch, folder2, fake_threads, marker_imread
):
    """预热 A 在途时换到 B：A 的结果不得注入，闭环对 B 补发预热（防丢拍）。"""
    from PySide6.QtWidgets import QApplication

    _open_folder(label_page, monkeypatch, folder2)
    adapter = FakeSamAdapter()
    label_page._sam_adapter = adapter
    label_page._apply_mode(AnnotationMode.INTERACTIVE)
    label_page._load_by_index(0)
    label_page._apply_mode(AnnotationMode.INTERACTIVE)
    QApplication.processEvents()
    labeler = label_page.controller._labeler
    assert labeler._image == "IMG::a.png"

    # 构造丢拍时序：warm(A) 已完成并排队 attach(A) 事件，但尚未投递
    label_page._warm_sam()  # busy=False → 同步完成，attach(A) 入队
    label_page.next_image()  # 换图 B：失效 + 同步 warm(B) + attach(B) 入队
    QApplication.processEvents()  # 依次投递 attach(A)→(B)→(B 补发)

    assert label_page._image_path.endswith("b.png")
    assert labeler._image == "IMG::b.png", (
        "旧图预热结果不得注入新画布——attach(A) 应被路径校验拦截并补发 B"
    )


@pytest.mark.unit
def test_switch_resets_mode_session_state(label_page, monkeypatch, folder2):
    """v7 P3-7：RegionSam 区域框换图清空。"""
    _open_folder(label_page, monkeypatch, folder2)
    adapter = FakeSamAdapter()
    label_page._sam_adapter = adapter

    label_page._apply_mode(AnnotationMode.REGION_SAM)
    region_labeler = label_page.controller._labeler
    region_labeler._box = (1.0, 1.0, 10.0, 10.0)

    monkeypatch.setattr(label_page, "_warm_sam", lambda: None)
    label_page.next_image()
    assert region_labeler._box is None, "换图应清 RegionSam 区域框"


# ============================== W55·v7 P2-4：操作员感知通道 ============================== #


class ExplodingAdapter:
    def predict_point(self, image, pt):
        raise RuntimeError("boom")

    def predict_point_in_box(self, image, pt, box):
        raise RuntimeError("boom-box")

    def predict_points(self, image, points, labels, mask_input=None):
        raise RuntimeError("boom-brush")


@pytest.mark.unit
def test_inference_exception_feeds_back_to_operator(qapp):
    """推理异常经反馈通道到达操作员（v7 P2-4：有日志也要有感知）。"""
    from labeling.controller import AnnotationController

    canvas = AnnotationCanvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.INTERACTIVE)
    labeler = ctrl._labeler
    labeler.set_adapter(ExplodingAdapter())
    labeler.set_image("IMG")
    got: list[tuple[str, str]] = []
    ctrl.set_feedback_callback(lambda k, m: got.append((k, m)))

    ctrl.handle_press((5.0, 5.0))

    assert got and got[0][0] == "error" and "boom" in got[0][1]


@pytest.mark.unit
def test_not_ready_click_warns_instead_of_silence(qapp):
    """未就绪（未加载/预热中）点击提示 warn，不再静默无操作。"""
    from labeling.controller import AnnotationController

    canvas = AnnotationCanvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.INTERACTIVE)
    labeler = ctrl._labeler
    got: list[tuple[str, str]] = []
    ctrl.set_feedback_callback(lambda k, m: got.append((k, m)))

    ctrl.handle_press((5.0, 5.0))  # adapter/image 双 None
    assert got and got[0][0] == "warn"

    got.clear()
    labeler.set_adapter(ExplodingAdapter())  # 换图失效窗口：有 adapter 无帧
    ctrl.handle_press((5.0, 5.0))
    assert got and got[0][0] == "warn", "预热中点击应提示而非静默"


@pytest.mark.unit
def test_auto_failure_vs_zero_detection_distinct(qapp):
    """AUTO 失败（-1/error）与真零检出（0/info）可区分（v7 P2-4 DoD）。"""
    from labeling.modes.auto import AutoLabeler

    got: list[tuple[str, str]] = []
    labeler = AutoLabeler("defect")
    labeler.set_feedback_callback(lambda k, m: got.append((k, m)))

    def boom(image):
        raise RuntimeError("engine down")

    labeler.set_detector(boom)
    labeler.set_image("IMG")
    assert labeler.run() == -1, "失败须返回哨兵 -1（与零检出 0 区分）"
    assert got and got[-1][0] == "error" and "engine down" in got[-1][1]

    got.clear()
    labeler.set_detector(lambda image: [])
    assert labeler.run() == 0
    assert got and got[-1][0] == "info", "真零检出应 info 提示而非静默"


@pytest.mark.unit
def test_region_sam_undefined_region_stays_silent(qapp):
    """RegionSam 未定区域/区域外点击是正常交互——不得刷「未就绪」。"""
    from labeling.controller import AnnotationController

    canvas = AnnotationCanvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.REGION_SAM)
    labeler = ctrl._labeler
    labeler.set_adapter(ExplodingAdapter())
    labeler.set_image("IMG")
    got: list[tuple[str, str]] = []
    ctrl.set_feedback_callback(lambda k, m: got.append((k, m)))

    # 未定区域单击（位移 < 阈值 = 单击语义）：正常忽略，无反馈
    ctrl.handle_press((10.0, 10.0))
    ctrl.handle_release((10.5, 10.5))
    assert got == []


@pytest.mark.unit
def test_page_wires_feedback_to_status_bar(
    label_page, monkeypatch, folder2, fake_threads, marker_imread
):
    """页面级接线：labeler 反馈直达 status_changed（v7 P2-4 全链）。"""
    _open_folder(label_page, monkeypatch, folder2)
    # 预置已加载假适配器——绕开权重选择对话框（offscreen 下模态挂起）
    label_page._sam_adapter = FakeSamAdapter()
    label_page._apply_mode(AnnotationMode.INTERACTIVE)
    labeler = label_page.controller._labeler
    labeler.set_adapter(ExplodingAdapter())
    labeler.set_image("IMG")

    label_page.controller.handle_press((5.0, 5.0))
    # W56·v7 P1-3 后 page 级反馈经异步回投（ADR 0003）——投递一跳队列事件
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()

    assert any(t == "推理失败" for t, _ in label_page._msgs), (
        "反馈应到达状态栏（经 controller→channel→回投→status_changed 链）"
    )
