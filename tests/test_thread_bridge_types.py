"""thread_bridge 载荷类型与调度可观测性测试（W14-C2，架构审查 P2-16）。

RED 背景（offscreen 实测复现，v2 审查文档 :295）：
(a) _to_qarg 对 None/tuple/numpy 标量一律 TypeError，而多数 worker
    except 元组不含 TypeError → 线程裸死、按钮永久禁用；
(b) invokeMethod 返回值被忽略——槽名拼错/漏 @Slot = 运行期无声空操作。

载荷语义（PySide6 6.11 offscreen 实测选定）：
- None 经 "QVariant" 通道原样送达 None，接收槽须声明 @Slot("QVariant")
  （Q_ARG(type(None))/Q_ARG(object) 抛 RuntimeError、Q_ARG(str, None) 送达乱码，
  三路均不可用——仅 "QVariant" 通道可靠往返）；
- tuple 经 "QVariantList" 通道送达后为 list（Qt 无 tuple 元类型，不保真）；
- numpy 标量（np.int64/np.float32/...）经 .item() 归一为 Python 标量后
  走既有 str/int/float 通道。
"""
from __future__ import annotations

import logging
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QObject, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ============================== _to_qarg 直调 ============================== #
@pytest.mark.unit
def test_to_qarg_accepts_none_tuple_numpy():
    """P2-16 RED：四种载荷此前一律 TypeError（类型表缺项），应全部可转换。"""
    from gui.core.thread_bridge import _to_qarg

    _to_qarg(None)
    _to_qarg((1, 2))
    _to_qarg(np.float32(0.5))
    _to_qarg(np.int64(3))


@pytest.mark.unit
def test_to_qarg_still_rejects_unsupported():
    """既有契约不削弱：重对象载荷仍显式 TypeError（对照 test_gui_core_tail）。"""
    from gui.core.thread_bridge import _to_qarg

    with pytest.raises(TypeError, match="不支持"):
        _to_qarg(object())


# ============================== 端到端送达 ============================== #
@pytest.mark.unit
def test_invoke_main_delivers_none_tuple_numpy(qapp):
    """四载荷经 invoke_main 队列事件实际送达（非仅不抛错）。"""
    from gui.core.thread_bridge import invoke_main

    class _Sink(QObject):
        got = []

        @Slot("QVariant")
        def rv(self, v):
            _Sink.got.append(("none", v))

        @Slot(list)
        def rl(self, v):
            _Sink.got.append(("tuple", v))

        @Slot(float)
        def rf(self, v):
            _Sink.got.append(("np_float", v))

        @Slot(int)
        def ri(self, v):
            _Sink.got.append(("np_int", v))

    sink = _Sink()
    _Sink.got = []
    invoke_main(sink, "rv", None)
    invoke_main(sink, "rl", (1, 2))
    invoke_main(sink, "rf", np.float32(0.5))
    invoke_main(sink, "ri", np.int64(3))
    qapp.processEvents()

    got = dict(_Sink.got)
    assert got["none"] is None, "None 应原样送达（经 QVariant 通道）"
    assert got["tuple"] == [1, 2], "tuple 送达为 list（QVariantList 语义）"
    assert got["np_float"] == 0.5
    assert got["np_int"] == 3


@pytest.mark.unit
def test_invoke_main_delivers_np_float64_subclass(qapp):
    """np.float64 是 float 子类但 type() 不等——归一路径须覆盖。"""
    from gui.core.thread_bridge import invoke_main

    class _Sink(QObject):
        got = []

        @Slot(float)
        def rf(self, v):
            _Sink.got.append(v)

    sink = _Sink()
    _Sink.got = []
    invoke_main(sink, "rf", np.float64(0.25))
    qapp.processEvents()
    assert _Sink.got == [0.25]


# ============================== 调度失败可观测性 ============================== #
@pytest.mark.unit
def test_invoke_main_warns_when_dispatch_fails(qapp, caplog):
    """P2-16(b) RED：invokeMethod 返回 False（槽缺失/无 @Slot/签名不匹配）
    此前静默丢弃；应告警且含目标类名与槽名，带参/无参两路都要告警。"""
    from gui.core.thread_bridge import invoke_main

    class _Sink(QObject):
        pass  # 故意无 no_such_slot 槽

    sink = _Sink()
    with caplog.at_level(logging.WARNING, logger="gui.core.thread_bridge"):
        invoke_main(sink, "no_such_slot", 5)   # 带参路径
        invoke_main(sink, "no_such_slot")      # 无参路径
    qapp.processEvents()

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 2, "带参与无参两条调度失败路径都应告警"
    assert all("no_such_slot" in r.getMessage() for r in warns)
    assert any("_Sink" in r.getMessage() for r in warns), "告警须含目标对象类名"


@pytest.mark.unit
def test_invoke_main_no_warning_on_success(qapp, caplog):
    """正常调度不得产生告警（防误报）。"""
    from gui.core.thread_bridge import invoke_main

    class _Sink(QObject):
        got = []

        @Slot(int)
        def ri(self, v):
            _Sink.got.append(v)

    sink = _Sink()
    _Sink.got = []
    with caplog.at_level(logging.WARNING, logger="gui.core.thread_bridge"):
        invoke_main(sink, "ri", 42)
    qapp.processEvents()

    assert _Sink.got == [42]
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not warns
