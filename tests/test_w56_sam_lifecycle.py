"""W56·v7 P2-5：SAM 状态机串行化。

四态 idle/loading/warming/predicting 唯一真源（str，GIL 原子），
_sam_busy 降为只读兼容属性。断言面：
① 状态→busy 映射；
② _ensure_sam 顶部重入守卫（加载在途双发加载 job 的竞态修复）；
③ 非 idle 态 _warm_sam 拒绝；
④ 异常路径（_sam_failed）状态复位。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from labeling.base import AnnotationMode  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def label_page(qapp):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    msgs: list[tuple[str, str]] = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


# ============================== ① 状态映射 ============================== #


@pytest.mark.unit
def test_busy_property_maps_state(label_page):
    assert label_page._sam_state == "idle"
    assert label_page._sam_busy is False

    label_page._sam_set_state("warming")
    assert label_page._sam_busy is True

    label_page._sam_set_state("loading")
    assert label_page._sam_busy is True

    label_page._sam_set_state("predicting")
    assert label_page._sam_busy is True

    label_page._sam_set_state("idle")
    assert label_page._sam_busy is False


# ============================== ② 重入守卫 ============================== #


@pytest.mark.unit
def test_ensure_sam_reentry_rejected_while_loading(label_page, monkeypatch):
    """加载在途再触发 _ensure_sam：拒绝并提示，不产生第二个加载 job。"""
    from gui.pages.label import sam_session as mod

    def _must_not_start(*a, **k):  # pragma: no cover - 守卫失效才到达
        raise AssertionError("加载在途不得再发加载任务（双发竞态）")

    monkeypatch.setattr(mod, "run_job", _must_not_start)
    monkeypatch.setattr(mod, "pick_open_file", _must_not_start)
    label_page._sam_set_state("loading")

    label_page._ensure_sam()

    assert label_page._sam_state == "loading"
    assert any(t == "SAM 处理中" for t, _ in label_page._msgs), (
        "重入应提示操作员而非静默"
    )


@pytest.mark.unit
def test_ensure_sam_reentry_rejected_while_warming(label_page, monkeypatch):
    from gui.pages.label import sam_session as mod

    def _must_not_start(*a, **k):  # pragma: no cover
        raise AssertionError("预热在途不得再发任务")

    monkeypatch.setattr(mod, "run_job", _must_not_start)
    label_page._sam_set_state("warming")

    label_page._ensure_sam()
    assert label_page._sam_state == "warming"


# ============================== ③ 非 idle 拒绝预热 ============================== #


@pytest.mark.unit
def test_warm_rejected_while_loading(label_page, monkeypatch):
    from gui.pages.label import sam_session as mod

    started: list[int] = []
    monkeypatch.setattr(mod, "run_job", lambda *a, **k: started.append(1))
    label_page._image_path = "x:/fake.png"
    label_page._sam_set_state("loading")

    label_page._warm_sam()

    assert started == [], "loading 在途不得并发进 warm（torch 串行约束）"


# ============================== ④ 异常复位 ============================== #


@pytest.mark.unit
def test_sam_failed_resets_state_to_idle(label_page):
    label_page._sam_set_state("loading")
    label_page._sam_failed("boom")
    assert label_page._sam_state == "idle"
    assert any(t == "SAM 加载失败" for t, _ in label_page._msgs)


# ============================== W56·v7 P1-3：异步推理（ADR 0003） ============================== #

import threading  # noqa: E402
import time  # noqa: E402


class _PolyAdapter:
    """同步/异步两用假适配器：记录执行线程与调用次数。"""

    def __init__(self, poly=None, exc=None):
        self.poly = poly or [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        self.exc = exc
        self.thread = None
        self.calls = 0

    def predict_point(self, image, pt):
        self.calls += 1
        self.thread = threading.current_thread()
        if self.exc:
            raise self.exc
        return self.poly


def _wire_async(label_page, monkeypatch):
    """接真异步通道（不经 _ensure_sam 对话框路径）+ fake_threads。"""
    import threading as _th

    from gui.pages.label.sam_session import _SamAsyncChannel

    class _FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target, self._args, self._kwargs = target, args, kwargs or {}

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(_th, "Thread", _FakeThread)
    label_page.controller.set_async_channel(_SamAsyncChannel(label_page))


@pytest.mark.unit
def test_predict_runs_off_gui_thread(label_page, monkeypatch):
    """DoD①：推理执行线程 ≠ GUI 主线程（真线程 + 轮询回投）。"""
    adapter = _PolyAdapter()
    label_page._sam_adapter = type("A", (), {"loaded": True})()
    label_page.controller.set_mode(AnnotationMode.INTERACTIVE)
    labeler = label_page.controller._labeler
    labeler.set_adapter(adapter)
    labeler.set_image("IMG")
    from gui.pages.label.sam_session import _SamAsyncChannel

    label_page.controller.set_async_channel(_SamAsyncChannel(label_page))

    label_page.controller.handle_press((5.0, 5.0))

    deadline = time.monotonic() + 5.0
    while label_page._sam_state != "idle" and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()

    assert adapter.calls == 1
    assert adapter.thread is not threading.main_thread(), (
        "推理必须离开 GUI 线程（v7 P1-3 主断言）"
    )
    assert labeler._pending is not None, "回投后 pending 形状应就位"


@pytest.mark.unit
def test_busy_second_click_rejected_not_sync_fallback(
    label_page, monkeypatch
):
    """DoD②：推理在途第二击被拒（页面提示），不回落 GUI 线程同步推理。"""
    _wire_async(label_page, monkeypatch)
    adapter = _PolyAdapter()
    label_page.controller.set_mode(AnnotationMode.INTERACTIVE)
    labeler = label_page.controller._labeler
    labeler.set_adapter(adapter)
    labeler.set_image("IMG")

    label_page.controller.handle_press((5.0, 5.0))  # 同步 worker：pending 入队
    assert label_page._sam_state == "predicting"  # 槽未投递前仍占用

    label_page.controller.handle_press((6.0, 6.0))  # 第二击：忙

    assert adapter.calls == 1, "忙时不得回落同步推理（击穿串行约束）"
    assert any(t == "SAM 处理中" for t, _ in label_page._msgs)
    QApplication.processEvents()
    assert label_page._sam_state == "idle"
    assert labeler._pending is not None


@pytest.mark.unit
def test_async_stale_result_discarded_on_image_change(
    label_page, monkeypatch
):
    """DoD③：推理在途换图——旧图结果回投时被陈旧校验丢弃（P1-2 闭环）。"""
    _wire_async(label_page, monkeypatch)
    adapter = _PolyAdapter()
    label_page.controller.set_mode(AnnotationMode.INTERACTIVE)
    labeler = label_page.controller._labeler
    labeler.set_adapter(adapter)
    labeler.set_image("IMG_A")

    label_page.controller.handle_press((5.0, 5.0))  # ctx.image = IMG_A
    labeler.set_image("IMG_B")  # 模拟换图失效→新帧注入

    QApplication.processEvents()

    assert labeler._pending is None, "旧图推理结果不得落到新帧画布"
    assert label_page._sam_state == "idle"


@pytest.mark.unit
def test_async_error_feeds_back(label_page, monkeypatch):
    """DoD④：worker 内推理异常经回投转为操作员 error 反馈。"""
    _wire_async(label_page, monkeypatch)
    adapter = _PolyAdapter(exc=RuntimeError("engine down"))
    label_page.controller.set_mode(AnnotationMode.INTERACTIVE)
    labeler = label_page.controller._labeler
    labeler.set_adapter(adapter)
    labeler.set_image("IMG")

    label_page.controller.handle_press((5.0, 5.0))
    QApplication.processEvents()

    assert label_page._sam_state == "idle"
    assert any(
        t == "推理失败" and "engine down" in a
        for t, a in label_page._msgs
    )


@pytest.mark.unit
def test_auto_async_sentinel_and_deliver():
    """DoD⑤：AUTO 异步受理返回 -2，deliver 回投建队（ADR 0003 契约）。"""
    from labeling.base import Shape
    from labeling.modes.auto import AutoLabeler

    class RecordingChannel:
        def __init__(self):
            self.submitted: list = []

        def submit(self, fn, tag):
            self.submitted.append((tag, fn()))
            return True

    shapes = [Shape(mode=AnnotationMode.POLYGON, points=((0, 0), (5, 0), (5, 5)))]
    labeler = AutoLabeler("defect", detector=lambda img: shapes, image="IMG")
    channel = RecordingChannel()
    labeler.set_async_channel(channel)

    assert labeler.run() == -2, "异步受理应返回 -2 哨兵"
    assert channel.submitted and channel.submitted[0][0] == "auto"

    labeler.deliver("auto", channel.submitted[0][1])
    assert labeler.pending_count == 1


# ============================== W56·v7 P2-1：卸载通道 ============================== #


class _UnloadableAdapter:
    def __init__(self):
        self.loaded = True
        self.unloaded = 0

    def set_image(self, img):
        pass

    def unload(self):
        self.unloaded += 1
        self.loaded = False


@pytest.mark.unit
def test_adapter_unload_idempotent_without_weights(qapp):
    """两 adapter 未加载态 unload 幂等不炸（torch 可缺席语义）。"""
    from labeling.sam3_adapter import Sam3Adapter
    from labeling.sam_adapter import SamAdapter

    a1 = SamAdapter()
    a1.unload()
    assert a1.loaded is False

    a3 = Sam3Adapter()
    a3.unload()
    assert a3.loaded is False


@pytest.mark.unit
def test_unload_sam_releases_session(label_page):
    """卸载：adapter 释放、页引用清空、labeler 帧失效、状态栏确认。"""
    adapter = _UnloadableAdapter()
    label_page._sam_adapter = adapter
    label_page.controller.set_mode(AnnotationMode.INTERACTIVE)
    labeler = label_page.controller._labeler
    labeler.set_image("IMG")

    label_page.unload_sam()

    assert adapter.unloaded == 1 and adapter.loaded is False
    assert label_page._sam_adapter is None
    assert label_page._pending_sam_image is None
    assert labeler._image is None, "卸载后 labeler 帧引用须失效"
    assert any(t == "SAM 已卸载" for t, _ in label_page._msgs)


@pytest.mark.unit
def test_unload_rejected_while_predicting(label_page):
    """推理在途拒绝卸载（防在途竞态，ADR 0003 串行约束）。"""
    adapter = _UnloadableAdapter()
    label_page._sam_adapter = adapter
    label_page._sam_set_state("predicting")

    label_page.unload_sam()

    assert adapter.unloaded == 0, "predicting 在途不得卸载"
    assert label_page._sam_state == "predicting"
    assert any(t == "SAM 处理中" for t, _ in label_page._msgs)


@pytest.mark.unit
def test_unload_without_loaded_adapter_is_noop(label_page):
    label_page._sam_adapter = None
    label_page.unload_sam()  # 不炸、提示无需卸载
    assert any("SAM 未加载" in a for _, a in label_page._msgs)


@pytest.mark.unit
def test_close_event_unloads_loaded_adapter(label_page):
    """页面关闭自动卸载（W56·v7 P2-1 收尾兜底）。"""
    adapter = _UnloadableAdapter()
    label_page._sam_adapter = adapter

    label_page.close()

    assert adapter.unloaded == 1


# ============================== W57·v7 P3 批：小项守卫 ============================== #


@pytest.mark.unit
def test_iou_thresh_domain_guard_both_backends(qapp):
    """P3-4：两后端 iou_thresh 越界拒收（[0,1]，语义分叉 docstring 注记）。"""
    import pytest as _pytest

    from labeling.sam3_adapter import Sam3Adapter
    from labeling.sam_adapter import SamAdapter

    with _pytest.raises(ValueError, match="iou_thresh"):
        Sam3Adapter().build_amg_detector(iou_thresh=1.5)
    with _pytest.raises(ValueError, match="iou_thresh"):
        SamAdapter().build_amg_detector(iou_thresh=-0.1)


@pytest.mark.unit
def test_sam3_backend_notice_on_load_path(label_page, monkeypatch):
    """P3-6：走 SAM3 装配链时能力差异一次性明示（诚实降级感知）。"""
    import threading as _th

    import labeling.sam3_adapter as sam3_mod

    class _FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target, self._args, self._kwargs = target, args, kwargs or {}

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

    class _FailingSam3:
        def load(self, model_dir, device="cuda"):
            raise OSError("weights not found")

    monkeypatch.setattr(_th, "Thread", _FakeThread)
    monkeypatch.setattr(sam3_mod, "Sam3Adapter", _FailingSam3)

    label_page._load_sam3("Z:/nonexistent-model-dir")

    assert any(
        "SAM3 后端不支持负点击" in a for _, a in label_page._msgs
    ), "后端能力差异应一次性提示"
    QApplication.processEvents()  # 投递加载失败队列事件
    assert any(t == "SAM 加载失败" for t, _ in label_page._msgs)
    assert label_page._sam_state == "idle"


@pytest.mark.unit
def test_sync_fallback_without_channel(qapp):
    """无通道（默认）保持同步语义——labeling 层单测/脚本消费面零变化。"""
    from labeling.canvas import AnnotationCanvas
    from labeling.controller import AnnotationController

    canvas = AnnotationCanvas()
    ctrl = AnnotationController(canvas, mode=AnnotationMode.INTERACTIVE)
    labeler = ctrl._labeler
    adapter = _PolyAdapter()
    labeler.set_adapter(adapter)
    labeler.set_image("IMG")

    ctrl.handle_press((5.0, 5.0))

    assert adapter.calls == 1
    assert adapter.thread is threading.main_thread(), "无通道=同步（ADR）"
    assert labeler._pending is not None
