"""gui/core 尾巴补测（W10-T5：shell 83% / tasks_ui 82% / theme 92% / thread_bridge 94%）。

shell：select 未知 id 早退、set_status 双标签、_toggle_theme 无管理器/有管理器、
_toggle_language 信号链、_toggle_maximize 双向、无边框拖动 press/move、
closeEvent 活动线程与批量分支 + 确认框 Yes/No + 注册表清理异常吞掉。
tasks_ui：registered_tasks 吞注册表异常、only_available 空注册表退化全量、
未注册任务过滤、缺引擎后缀与 tooltip（假注册表注入，不动真注册表）。
theme：resolve_theme styleHints 异常回退 night、ThemeManager.toggle 往返。
thread_bridge：invoke_main 无参 QueuedConnection 分支、不支持载荷 TypeError。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")  # 无 PySide6 则跳过本模块

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (  # noqa: E402
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    Qt,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QMessageBox,
    QPushButton,
    QWidget,
)

from core.interfaces_supervised import TaskType  # noqa: E402
from gui.core.i18n import current_language, set_language, tr  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_native_dialogs(monkeypatch):
    """offscreen 安全网：未被测例显式打桩的原生确认框一律返回 No，绝不真弹。"""
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )


@pytest.fixture(autouse=True)
def _restore_language_and_theme():
    """语言/主题是模块级全局，测试后还原避免污染其他用例。"""
    lang = current_language()
    yield
    set_language(lang)
    from gui.core import theme as theme_mod

    if theme_mod.current_theme() != "night":
        app = QApplication.instance()
        if app is not None:
            from gui.core.theme import ThemeManager

            ThemeManager(app).apply("night")
        theme_mod._current = "night"


# ============================== shell.MainWindow ============================== #


@pytest.fixture
def win(qapp):
    from gui.core.shell import MainWindow

    w = MainWindow("TailTest")
    yield w
    # teardown 先中和"活动"标记再 close：否则 closeEvent 会弹真 QMessageBox，
    # offscreen 下永久阻塞（monkeypatch 届时已撤销）
    for page in w._pages.values():
        if getattr(page, "_worker", None) is not None:
            page._worker = None
        btn_batch = getattr(page, "_btn_batch", None)
        if btn_batch is not None and not btn_batch.isEnabled():
            btn_batch.setEnabled(True)
    w.close()


class _RecordingThemeManager:
    """记录 apply 调用的假主题管理器。"""

    def __init__(self, theme: str = "night") -> None:
        self.theme = theme
        self.applied: list[str] = []

    def apply(self, theme: str) -> None:
        self.applied.append(theme)
        self.theme = theme


@pytest.mark.unit
def test_add_page_select_and_unknown_key(win, monkeypatch):
    w1, w2, w3 = QWidget(), QWidget(), QWidget()
    win.add_page("a", "ico_a", "页面A", w1)
    win.add_page("b", "ico_b", "页面B", w2)
    assert win._stack.count() == 2
    assert set(win._nav_buttons) == {"a", "b"}

    # 重复 id：特征测试——现行为为覆盖映射、栈与导航再各添一份
    win.add_page("a", "ico_a", "页面A2", w3)
    assert win._pages["a"] is w3
    assert win._stack.count() == 3
    assert win._nav_buttons["a"].text().strip() == "页面A2"

    # W39：未登录=operator 最小集且页面矩阵只认正式页 id——本测用任意
    # key 验证 select 机制，旁路门控（门控行为由 test_w29_permissions 覆盖）
    from gui.core import shell as shell_mod

    monkeypatch.setattr(shell_mod, "page_allowed", lambda role, key: True)
    win.select("b")
    assert win._stack.currentWidget() is w2
    assert win._nav_buttons["b"].property("selected") is True
    assert win._nav_buttons["a"].property("selected") is False

    # 未知 id：早退，不切换页面
    win.select("no_such_page")
    assert win._stack.currentWidget() is w2


@pytest.mark.unit
def test_set_status_text_and_accent(win):
    win.set_status("推理中", "GPU 78%")
    assert win._status_text.text() == "推理中"
    assert win._status_accent.text() == "GPU 78%"
    win.set_status("就绪")
    assert win._status_text.text() == "就绪"
    assert win._status_accent.text() == ""


@pytest.mark.unit
def test_toggle_theme_without_manager_is_noop(win):
    win._toggle_theme()  # 未 attach_theme → 直接返回，不崩
    assert win._theme_manager is None


@pytest.mark.unit
def test_toggle_theme_with_manager_emits_signal(win):
    mgr = _RecordingThemeManager("night")
    win.attach_theme(mgr)
    emitted: list[str] = []
    win.theme_changed.connect(emitted.append)

    win._toggle_theme()  # night → daytime
    assert mgr.applied == ["daytime"]
    assert emitted == ["daytime"]

    win._toggle_theme()  # daytime → night
    assert mgr.applied == ["daytime", "night"]
    assert emitted == ["daytime", "night"]


@pytest.mark.unit
def test_toggle_language_signal_chain(win):
    set_language("ch_CN")
    emitted: list[str] = []
    win.language_changed.connect(emitted.append)

    win._toggle_language()
    assert current_language() == "en_US"
    assert emitted == ["en_US"]

    win._toggle_language()
    assert current_language() == "ch_CN"
    assert emitted == ["en_US", "ch_CN"]


@pytest.mark.unit
def test_toggle_maximize_roundtrip(qapp, win):
    win.setGeometry(50, 60, 1200, 760)
    win.show()
    qapp.processEvents()
    assert win.isMaximized() is False

    win._toggle_maximize()  # 未最大化 → 最大化分支
    qapp.processEvents()
    assert win.isMaximized() is True
    assert win._btn_max.text() == "❐"  # ❐
    assert win._prev_geometry == QRect(50, 60, 1200, 760)

    win._toggle_maximize()  # 已最大化 → 还原分支
    qapp.processEvents()
    assert win.isMaximized() is False
    assert win._btn_max.text() == "□"  # □
    assert win.geometry() == QRect(50, 60, 1200, 760)


def _press(local: QPointF, glob: QPointF, button: Qt.MouseButton) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress, local, glob,
        button, button, Qt.KeyboardModifier.NoModifier,
    )


@pytest.mark.unit
def test_frameless_drag_press_and_move(qapp, win):
    win.setGeometry(100, 100, 1200, 760)
    win.show()
    qapp.processEvents()
    top_left = win.frameGeometry().topLeft()

    win.mousePressEvent(_press(QPointF(8, 8), QPointF(300, 200), Qt.MouseButton.LeftButton))
    assert hasattr(win, "_drag_pos")
    assert win._drag_pos == QPoint(300, 200) - top_left

    move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(58, 58), QPointF(360, 250),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.mouseMoveEvent(move)
    qapp.processEvents()
    assert win.pos() == QPoint(360, 250) - win._drag_pos


@pytest.mark.unit
def test_drag_non_left_button_does_not_start(win):
    win.mousePressEvent(_press(QPointF(8, 8), QPointF(300, 200), Qt.MouseButton.RightButton))
    assert not hasattr(win, "_drag_pos")

    move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(58, 58), QPointF(360, 250),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.mouseMoveEvent(move)  # 无 _drag_pos → 不动也不崩
    assert not hasattr(win, "_drag_pos")


# ============================== shell.closeEvent ============================== #


class _FakeWorker:
    def __init__(self, running: bool) -> None:
        self._running = running

    def isRunning(self) -> bool:
        return self._running


def _close_evt() -> QCloseEvent:
    ev = QCloseEvent()
    assert ev.isAccepted() is True  # 默认 accepted；ignore/accept 才有分辨力
    return ev


@pytest.mark.unit
def test_close_event_idle_pages_accept_without_question(win, monkeypatch):
    called: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: called.append(a) or QMessageBox.No)
    )
    page = QWidget()
    page._worker = _FakeWorker(False)  # 有 worker 但不在跑
    win.add_page("p", "i", "P", page)

    ev = _close_evt()
    win.closeEvent(ev)
    assert called == []            # 无活动 → 不弹确认框
    assert ev.isAccepted() is True


@pytest.mark.unit
def test_close_event_running_worker_no_ignores(win, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    page = QWidget()
    page._worker = _FakeWorker(True)
    win.add_page("p", "i", "P", page)

    ev = _close_evt()
    win.closeEvent(ev)
    assert ev.isAccepted() is False  # 取消 → event.ignore()


@pytest.mark.unit
def test_close_event_running_worker_yes_accepts(win, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    page = QWidget()
    page._worker = _FakeWorker(True)
    win.add_page("p", "i", "P", page)

    ev = _close_evt()
    win.closeEvent(ev)
    assert ev.isAccepted() is True  # 确认 → 放行


@pytest.mark.unit
def test_close_event_disabled_batch_button_counts_as_active(win, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    page = QWidget()
    page._batch_cancel = False
    batch_btn = QPushButton("批量")
    batch_btn.setEnabled(False)  # 批量推理进行中的既有约定：按钮禁用
    page._btn_batch = batch_btn
    win.add_page("p", "i", "P", page)

    ev = _close_evt()
    win.closeEvent(ev)
    assert ev.isAccepted() is False  # 批量进行中 → No 视为活动 → ignore


@pytest.mark.unit
def test_close_event_enabled_batch_button_not_active(win, monkeypatch):
    called: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: called.append(a) or QMessageBox.Yes)
    )
    page = QWidget()
    page._batch_cancel = False
    page._btn_batch = QPushButton("批量")  # enabled
    win.add_page("p", "i", "P", page)

    ev = _close_evt()
    win.closeEvent(ev)
    assert called == []
    assert ev.isAccepted() is True


@pytest.mark.unit
def test_close_event_registry_clear_failure_still_accepts(win, monkeypatch):
    import models.supervised.registry as reg_mod

    def _boom():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(reg_mod, "get_default_registry", _boom)

    ev = _close_evt()
    win.closeEvent(ev)  # 清缓存失败须被吞掉（debug 日志），不得阻断退出
    assert ev.isAccepted() is True


@pytest.mark.unit
def test_close_event_real_registry_cleared_and_accepts(win, monkeypatch):
    import models.supervised.registry as reg_mod

    real_reg = reg_mod.get_default_registry()
    cleared: list[bool] = []
    orig_clear = real_reg.clear_cache
    monkeypatch.setattr(
        real_reg,
        "clear_cache",
        lambda *a, **k: cleared.append(True) or orig_clear(*a, **k),
    )

    ev = _close_evt()
    win.closeEvent(ev)
    assert ev.isAccepted() is True
    assert cleared == [True]  # 正常退出路径必须真清引擎实例缓存


# ============================== tasks_ui ============================== #


class _FakeRegistry:
    def __init__(self, tasks) -> None:
        self._tasks = list(tasks)

    def list(self):
        return list(self._tasks)


def _patch_registry(monkeypatch, tasks) -> None:
    import models.supervised.registry as reg_mod

    fake = _FakeRegistry(tasks)
    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: fake)


@pytest.mark.unit
def test_registered_tasks_swallows_registry_failure(monkeypatch):
    import models.supervised.registry as reg_mod

    def _boom():
        raise RuntimeError("registry down")

    monkeypatch.setattr(reg_mod, "get_default_registry", _boom)
    from gui.core.tasks_ui import registered_tasks

    assert registered_tasks() == set()  # 注册表不可用 → 空（不裸穿）


@pytest.mark.unit
def test_populate_only_available_empty_registry_degrades_to_full(qapp, monkeypatch):
    _patch_registry(monkeypatch, [])
    from gui.core.tasks_ui import populate_task_combo

    combo = QComboBox()
    items = populate_task_combo(
        combo,
        only_available=True,  # 注册表全空 → 强制退化为全量，避免空下拉
        unavailable_suffix="（X未装）",
        unavailable_tooltip="TT 缺引擎",
    )
    assert len(items) == len(TaskType) == 10  # W32：+OCR
    assert all(ok is False for _, ok in items)
    assert combo.itemData(0) is TaskType.DET  # UIA 兼容首项
    assert "（X未装）" in combo.itemText(0)
    assert combo.itemData(0, Qt.ItemDataRole.ToolTipRole) == tr("TT 缺引擎")


@pytest.mark.unit
def test_populate_only_available_filters_unregistered(qapp, monkeypatch):
    _patch_registry(monkeypatch, [TaskType.DET, TaskType.SEG])
    from gui.core.tasks_ui import populate_task_combo

    combo = QComboBox()
    items = populate_task_combo(combo, only_available=True)
    assert [t for t, _ in items] == [TaskType.DET, TaskType.SEG]  # 枚举序
    assert all(ok for _, ok in items)
    assert combo.count() == 2
    assert combo.itemData(0) is TaskType.DET
    assert "（未装引擎）" not in combo.itemText(0)


@pytest.mark.unit
def test_populate_all_marks_unavailable_suffix_and_tooltip(qapp, monkeypatch):
    _patch_registry(monkeypatch, [TaskType.DET])
    from gui.core.tasks_ui import populate_task_combo

    combo = QComboBox()
    items = populate_task_combo(
        combo,
        only_available=False,
        unavailable_suffix="（未装引擎）",
        unavailable_tooltip="该任务引擎未安装",
    )
    assert len(items) == 10  # W32：+OCR
    det_seen = 0
    for i, (task, ok) in enumerate(items):
        assert combo.itemData(i) is task
        if ok:
            det_seen += 1
            assert task is TaskType.DET
            assert "（未装引擎）" not in combo.itemText(i)
            assert combo.itemData(i, Qt.ItemDataRole.ToolTipRole) is None
        else:
            assert "（未装引擎）" in combo.itemText(i)
            assert combo.itemData(i, Qt.ItemDataRole.ToolTipRole) == tr("该任务引擎未安装")
    assert det_seen == 1


# ============================== theme ============================== #


@pytest.mark.unit
def test_resolve_theme_falls_back_to_night_when_stylehints_fails(qapp, monkeypatch):
    class _BrokenGui:
        @staticmethod
        def styleHints():
            raise RuntimeError("styleHints unavailable")

    monkeypatch.setattr("PySide6.QtGui.QGuiApplication", _BrokenGui)
    from gui.core.theme import resolve_theme

    assert resolve_theme("auto") == "night"  # 异常回退 night，不裸穿


@pytest.mark.unit
def test_manager_toggle_roundtrip_and_apply_theme(qapp):
    from gui.core.theme import ThemeManager, apply_theme, current_theme

    mgr = ThemeManager(qapp)
    mgr.apply("night")

    assert mgr.toggle() == "daytime"
    assert mgr.theme == "daytime"
    assert current_theme() == "daytime"

    assert mgr.toggle() == "night"
    assert mgr.theme == "night"
    assert current_theme() == "night"

    # 便捷入口同样返回可继续切换的管理器
    mgr2 = apply_theme(qapp, "night")
    assert isinstance(mgr2, ThemeManager)
    assert mgr2.theme == "night"


# ============================== thread_bridge ============================== #


class _BridgeTarget(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.ping_count = 0

    @Slot()
    def ping(self) -> None:
        self.ping_count += 1


@pytest.mark.unit
def test_invoke_main_no_args_queued_until_flush(qapp):
    from gui.core.thread_bridge import invoke_main

    target = _BridgeTarget()
    invoke_main(target, "ping")
    assert target.ping_count == 0  # QueuedConnection：冲刷前不得同步执行
    qapp.processEvents()
    assert target.ping_count == 1


@pytest.mark.unit
def test_invoke_main_rejects_unsupported_payload(qapp):
    from gui.core.thread_bridge import invoke_main

    target = _BridgeTarget()
    with pytest.raises(TypeError, match="不支持"):
        invoke_main(target, "ping", object())  # 重对象载荷必须显式拒绝
    assert target.ping_count == 0
