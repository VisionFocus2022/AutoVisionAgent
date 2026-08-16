"""GUI 冒烟测试（FR-D）：主壳组装 + 标注页画布接入 + 导航/主题（offscreen）。

M2 更新：适配 10 页导航树 + 默认登录页。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")  # 无 PySide6 则跳过

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.core.theme import ThemeManager  # noqa: E402
from gui.main import build_window  # noqa: E402
from labeling import AnnotationMode  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    mgr = ThemeManager(qapp)
    mgr.apply("night")
    w = build_window()
    w.attach_theme(mgr)
    w.show()
    yield w
    w.close()


@pytest.mark.unit
def test_window_registers_pages(window):
    # W1: 11 pages（flaw_gen 为 era-2 后新增，旧测试停在 10）
    assert window._stack.count() == 11
    assert "label" in window._pages


@pytest.fixture
def label_page(window):
    return window._pages["label"]


@pytest.mark.unit
def test_label_page_rectangle_and_undo(label_page):
    label_page._apply_mode(AnnotationMode.RECTANGLE)
    label_page.controller.handle_press((50, 50))
    label_page.controller.handle_move((200, 150))
    label_page.controller.handle_release((200, 150))
    assert len(label_page.canvas.shapes) == 1
    assert label_page.canvas.shapes[0].mode is AnnotationMode.RECTANGLE

    assert label_page.canvas.undo()
    assert len(label_page.canvas.shapes) == 0
    assert label_page.btn_undo.isEnabled() is False


@pytest.mark.unit
@pytest.mark.xfail(reason="era-2 多边形 commit 闭合语义 v2.0 未恢复（W2：闭合+吸附+drain 一并恢复）", strict=True)
def test_label_page_polygon_commit(label_page):
    label_page._apply_mode(AnnotationMode.POLYGON)
    for pt in [(10, 10), (80, 10), (80, 80), (10, 80)]:
        label_page.controller.handle_press((float(pt[0]), float(pt[1])))
    label_page.controller.handle_commit()
    assert len(label_page.canvas.shapes) == 1
    sh = label_page.canvas.shapes[0]
    assert sh.points[0] == sh.points[-1]


@pytest.mark.unit
def test_nav_switch(window):
    window.select("label")
    label_idx = window._stack.currentIndex()
    assert label_idx >= 0
    window.select("train")
    assert window._stack.currentIndex() != label_idx
    window.select("label")
    assert window._stack.currentIndex() == label_idx
    label_btn = window._nav_buttons["label"]
    assert label_btn.property("selected") is True


@pytest.mark.unit
def test_theme_toggle(window):
    from gui.core.theme import current_theme

    window._toggle_theme()
    assert current_theme() == "daytime"
    window._toggle_theme()
    assert current_theme() == "night"


@pytest.mark.unit
def test_label_list_refresh(label_page):
    label_page._apply_mode(AnnotationMode.RECTANGLE)
    label_page.controller.handle_press((10, 10))
    label_page.controller.handle_release((60, 60))
    label_page._apply_mode(AnnotationMode.KEYPOINT)
    label_page.controller.handle_press((30, 30))
    label_page.controller.handle_release((30, 30))
    assert label_page.shape_list.count() == 2
