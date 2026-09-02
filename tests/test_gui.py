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
    # W39：未登录=operator 最小集（train 不可见）——本测关注切换机制，
    # 以 admin 角色隔离门控语义（门控行为由 test_w29_permissions 覆盖）
    window.set_role("admin")
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
    label_page._apply_mode(AnnotationMode.RECTANGLE)
    label_page.controller.handle_press((30, 30))
    label_page.controller.handle_release((70, 70))
    assert label_page.shape_list.count() == 2


# ---------------------------------------------------------------------------
# W14 C5 P2-12：页面注册表单源（gui.pages 必须导出主窗口注册的全部 11 页）
# ---------------------------------------------------------------------------

_PAGE_ATTRS = {
    "login": "LoginPage",
    "home": "HomePage",
    "label": "LabelPage",
    "data_manage": "DataManagePage",
    "train": "TrainPage",
    "predict": "PredictPage",
    "eval": "EvalPage",
    "deploy": "DeployPage",
    "flaw_gen": "FlawGenPage",
    "project": "ProjectPage",
    "settings": "SettingsPage",
}


@pytest.mark.unit
def test_pages_registry_exports_all_11_pages(window):
    """gui.pages 注册表导出与主窗口实际注册页一一对应（防 flaw_gen 式漏导出）。"""
    import gui.pages as pages_reg

    exported = set(getattr(pages_reg, "__all__", []))
    for page_id, attr in _PAGE_ATTRS.items():
        assert attr in exported, f"gui.pages.__all__ 缺少 {attr}"
        cls = getattr(pages_reg, attr, None)
        assert cls is not None, f"gui.pages 缺少导出 {attr}"
        page = window._pages[page_id]
        assert isinstance(page, cls), f"{page_id} 页应为 {attr} 实例"


@pytest.mark.unit
def test_main_imports_pages_via_registry_only():
    """gui/main.py 页面导入必须经 gui.pages 注册表（禁止 deep import 双真源）。"""
    import ast
    from pathlib import Path

    from gui import main as gui_main

    src = Path(gui_main.__file__).read_text(encoding="utf-8")
    deep = [
        node.module
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("gui.pages.")
    ]
    assert deep == [], f"gui/main.py 存在绕过注册表的 deep import: {deep}"


# ---------------------------------------------------------------------------
# W14 C5 P2-14：单实例互斥（QLockFile）——双开将造成 user_settings.json /
# 日志轮转文件双写竞争
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_single_instance_second_acquire_returns_false(qapp, tmp_path):
    """锁被占用时（含同进程第二个 QLockFile）acquire 必须返回 False。"""
    from PySide6.QtCore import QLockFile

    from gui.main import acquire_single_instance_lock

    lock_path = str(tmp_path / "ava-single.lock")
    holder = QLockFile(lock_path)
    assert holder.tryLock(0) is True  # 同进程首个 QLockFile 持锁成功
    # 同路径再 acquire（模拟第二实例）必须失败
    assert acquire_single_instance_lock(lock_path) is False
    holder.unlock()
    # 释放后可重新获得
    assert acquire_single_instance_lock(lock_path) is True


@pytest.mark.unit
def test_single_instance_default_lock_path_in_temp(qapp):
    from gui.main import default_single_instance_lock_path

    path = default_single_instance_lock_path()
    assert os.path.basename(path) == "autovisionagent-single-instance.lock"
    assert os.path.isdir(os.path.dirname(path))


@pytest.mark.unit
def test_main_exits_with_message_when_already_running(qapp, monkeypatch):
    """已有实例运行时：main() 弹提示并返回非零退出码，不构建窗口。"""
    import gui.main as main_mod

    called = {}
    monkeypatch.setattr(
        main_mod, "acquire_single_instance_lock", lambda *a, **k: False
    )
    monkeypatch.setattr(
        main_mod.QMessageBox, "warning",
        staticmethod(lambda *a, **k: called.setdefault("warned", a)),
    )

    def _boom():
        raise AssertionError("already-running 分支不应构建窗口")

    monkeypatch.setattr(main_mod, "build_window", _boom)

    rc = main_mod.main()
    assert rc == 1
    assert "warned" in called, "二次启动必须弹出已运行提示"
