"""W59c：工作流「下一步」向导导航（PRD docs/prd-workflow-next-step.md）。

覆盖：① shell add_page 对 request_page 信号的泛化挂接（有则切页、无则
零侵入）；② 三处按钮 emit 正确目标页 key；③ operator 角色被既有权限
门拦截（不切换 + 状态反馈，审计走 select 既有路径）。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ============================== ① shell 泛化挂接 ============================== #


@pytest.mark.unit
def test_shell_hooks_request_page_signal(qapp, monkeypatch):
    from gui.core.shell import MainWindow

    win = MainWindow()

    class _Page(QWidget):
        request_page = Signal(str)

    with_page, plain = _Page(), QWidget()
    win.add_page("label", "label", "标注", with_page)
    win.add_page("data_manage", "data", "数据管理", plain)
    win.set_role("admin")

    with_page.request_page.emit("data_manage")
    assert win._stack.currentWidget() is plain, "request_page 应经 select 切页"

    plain_key = getattr(plain, "request_page", None)
    assert plain_key is None, "无信号页零侵入（不注入属性）"


@pytest.mark.unit
def test_shell_denies_operator_train(qapp):
    from gui.core.shell import MainWindow

    win = MainWindow()

    class _Page(QWidget):
        request_page = Signal(str)

    dm, train = _Page(), QWidget()
    win.add_page("data_manage", "data", "数据管理", dm)
    win.add_page("train", "train", "训练", train)
    win.set_role("operator")
    win.select("data_manage")
    assert win._stack.currentWidget() is dm

    dm.request_page.emit("train")
    assert win._stack.currentWidget() is dm, "operator 无 train 页——不得切换"
    assert "无权限" in win._status_text.text(), "须有状态反馈（既有门行为）"


# ============================== ② 三处按钮 emit ============================== #


def _click_next(page, attr_suffix):
    btn = getattr(page, f"btn_goto_{attr_suffix}")
    got: list[str] = []
    page.request_page.connect(lambda k: got.append(k))
    btn.click()
    return got


@pytest.mark.unit
def test_label_page_next_button(qapp):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    page._thumb_pool.clear()
    assert _click_next(page, "data") == ["data_manage"]
    page._thumb_pool.clear()


@pytest.mark.unit
def test_data_manage_page_next_button(qapp):
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    page._thumb_pool.clear()
    assert _click_next(page, "train") == ["train"]
    page._thumb_pool.clear()


@pytest.mark.unit
def test_train_page_next_button(qapp):
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    assert _click_next(page, "predict") == ["predict"]
