"""project/home/settings/main/thumbnail 杂项测试（W9-T5：66%/72%/73%/48% → 填平）。

project：创建→列表(★)→打开（project_opened）→删除（No 保留/Yes 删除）。
home：统计卡片、最近项目、检测历史三态、快捷导航。settings：全键恢复与
路径选择。gui/main：build_window 离屏全量组装 + 项目打开联动 + setup_logging
（root handler 事后清理）。ThumbnailTask：QImage 成功/失败信号。
"""
from __future__ import annotations

import json
import logging
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    """把 ~/ 展开重定向到 tmp（ProjectPage 默认根与 recent 落盘都在这）。"""
    monkeypatch.setattr(
        "os.path.expanduser",
        lambda p: str(tmp_path) if p.startswith("~") else p,
    )
    return tmp_path


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


# ============================== project 页 ============================== #
@pytest.fixture
def proj_page(qapp, home_env):
    from gui.pages.project.page import ProjectPage

    page = ProjectPage()
    msgs, opened = [], []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page.project_opened.connect(lambda p: opened.append(p))
    page._msgs, page._opened = msgs, opened
    return page


@pytest.mark.unit
def test_project_create_list_open_and_recent_star(proj_page, home_env):
    proj_page.txt_name.setText("demo")
    proj_page._create_project()
    assert any(t == "项目已创建" for t, _ in proj_page._msgs)
    assert proj_page.project_list.count() == 1
    assert "(★)" in proj_page.project_list.item(0).text()  # 刚创建即在 recent
    from core.interfaces_supervised import TaskType

    assert proj_page._counter_labels[TaskType.DET].text() == "1"

    proj_page.project_list.setCurrentRow(0)
    proj_page._open_project()
    assert len(proj_page._opened) == 1
    assert proj_page._opened[0].startswith(str(home_env))
    assert any(t == "已打开" for t, _ in proj_page._msgs)


@pytest.mark.unit
def test_project_create_requires_name(proj_page):
    proj_page.txt_name.clear()
    proj_page._create_project()
    assert any("请输入项目名" in t for t, _ in proj_page._msgs)


@pytest.mark.unit
def test_project_open_without_selection(proj_page):
    proj_page._open_project()
    assert any("请先选择项目" in t for t, _ in proj_page._msgs)


@pytest.mark.unit
def test_project_delete_confirm_flow(proj_page, monkeypatch):
    proj_page.txt_name.setText("delme")
    proj_page._create_project()
    pid = proj_page.project_list.item(0).data(0x0100)  # Qt.UserRole
    path = pid.to_path(proj_page._base_root)
    assert os.path.isdir(path)

    proj_page.project_list.setCurrentRow(0)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No)
    )
    proj_page._delete_project()
    assert os.path.isdir(path)  # No → 保留

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    proj_page._delete_project()
    assert not os.path.isdir(path)
    assert any(t == "已删除" for t, _ in proj_page._msgs)
    assert proj_page.project_list.count() == 0


@pytest.mark.unit
def test_project_browse_root_resets_store(proj_page, monkeypatch, tmp_path):
    from gui.pages.project import page as proj_mod

    new_root = tmp_path / "other_root"
    new_root.mkdir()
    monkeypatch.setattr(proj_mod, "pick_directory", lambda *a, **k: str(new_root))
    proj_page._browse_root()
    assert proj_page._base_root == str(new_root)
    assert proj_page.project_list.count() == 0


# ============================== home 页 ============================== #
@pytest.mark.unit
def test_home_update_stats_and_shortcuts(qapp):
    from gui.pages.home.page import HomePage

    page = HomePage()
    page.update_stats(projects=3, images=10, models=2, gpu="CPU")
    assert page._card_projects._value_label.text() == "3"
    assert page._card_gpus._value_label.text() == "CPU"

    nav = []
    page.navigate.connect(nav.append)
    btns = [b for b in page.findChildren(QPushButton) if b.text() == "模型推理"]
    btns[0].click()
    assert nav == ["predict"]


@pytest.mark.unit
def test_home_refresh_recent_empty_and_filled(qapp, home_env):
    from gui.pages.home.page import HomePage
    from project.recent import add_recent

    page = HomePage()
    page.refresh_recent(str(home_env))
    assert page._recent_list.count() == 1
    assert "暂无最近项目" in page._recent_list.item(0).text()

    add_recent(str(home_env), "proj_det_001")
    page.refresh_recent(str(home_env))
    assert page._recent_list.count() == 1
    assert page._recent_list.item(0).text() == "proj_det_001"


@pytest.mark.unit
def test_home_refresh_history_three_states(qapp, monkeypatch):
    from gui.pages.home.page import HomePage

    page = HomePage()

    class _Hist0:
        def stats(self):
            return {"total": 0}

    monkeypatch.setattr("core.detection_history.get_history", lambda: _Hist0())
    page.refresh_history()
    assert page._history_label.text() == "暂无检测记录"

    class _Hist2:
        def stats(self):
            return {"total": 2, "avg_score": 0.5, "by_task": {"det": 2}}

    monkeypatch.setattr("core.detection_history.get_history", lambda: _Hist2())
    page.refresh_history()
    assert "推理总数: 2" in page._history_label.text()
    assert "det:2" in page._history_label.text()

    def _boom():
        raise OSError("db locked")

    monkeypatch.setattr("core.detection_history.get_history", _boom)
    page.refresh_history()
    assert page._history_label.text() == "暂无检测记录"  # 异常回退


@pytest.mark.unit
def test_home_recent_click_navigates(qapp):
    from gui.pages.home.page import HomePage
    from PySide6.QtWidgets import QListWidgetItem

    page = HomePage()
    nav = []
    page.navigate.connect(nav.append)
    page._on_recent_clicked(QListWidgetItem("x"))
    assert nav == ["project"]


# ============================== settings 页 ============================== #
@pytest.mark.unit
def test_settings_load_all_keys(qapp, tmp_path, monkeypatch):
    from gui.pages.settings import page as settings_mod

    (tmp_path / "user_settings.json").write_text(json.dumps({
        "theme": "auto", "language": "en_US", "device": "cpu",
        "precision": "fp16", "workspace": "W", "cache_dir": "C",
    }), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "_CONFIG_DIR", tmp_path)
    page = settings_mod.SettingsPage()
    assert page._theme_combo.currentIndex() == 2
    assert page._lang_combo.currentIndex() == 1
    assert page._device_combo.currentIndex() == 1
    assert page._precision_combo.currentIndex() == 1
    assert page._workspace_edit.text() == "W"
    assert page._cache_edit.text() == "C"
    from gui.core.i18n import set_language

    set_language("ch_CN")  # 语言被 en_US 联动改掉，恢复全局默认


@pytest.mark.unit
def test_settings_load_bad_json_tolerated(qapp, tmp_path, monkeypatch):
    from gui.pages.settings import page as settings_mod

    (tmp_path / "user_settings.json").write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(settings_mod, "_CONFIG_DIR", tmp_path)
    page = settings_mod.SettingsPage()
    assert page._theme_combo.currentIndex() == 0  # 默认值


@pytest.mark.unit
def test_settings_picks_and_save_full_fields(qapp, tmp_path, monkeypatch):
    from gui.pages.settings import page as settings_mod

    monkeypatch.setattr(settings_mod, "_CONFIG_DIR", tmp_path)
    page = settings_mod.SettingsPage()
    monkeypatch.setattr(
        "gui.widgets.file_dialog.pick_directory",
        lambda *a, **k: str(tmp_path / "ws"),
    )
    page._pick_workspace()
    page._pick_cache()
    assert page._workspace_edit.text().endswith("ws")

    page._device_combo.setCurrentIndex(1)
    page._precision_combo.setCurrentIndex(2)
    page._save()
    saved = json.loads((tmp_path / "user_settings.json").read_text("utf-8"))
    assert saved["device"] == "cpu"
    assert saved["precision"] == "int8"
    assert saved["workspace"].endswith("ws")
    from gui.core.i18n import set_language

    set_language("ch_CN")


# ============================== gui/main ============================== #
@pytest.mark.unit
def test_load_user_settings_returns_dict():
    from gui.main import _load_user_settings

    settings = _load_user_settings()
    assert isinstance(settings, dict)


@pytest.mark.unit
def test_setup_logging_writes_file_and_cleans_up(tmp_path, monkeypatch):
    import gui.main as main_mod

    log_dir = tmp_path / "logs"
    monkeypatch.chdir(tmp_path)  # 默认 log_dir=./logs → 落在 tmp
    before = list(logging.getLogger().handlers)
    main_mod.setup_logging()
    assert (log_dir / "autovision.log").exists()

    # 清理新增的 root handlers，避免污染后续测试日志流
    root = logging.getLogger()
    for h in list(root.handlers):
        if h not in before:
            h.close()
            root.removeHandler(h)


@pytest.mark.unit
def test_build_window_assembles_and_wires(qapp, tmp_path, home_env, monkeypatch):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)  # 防默认 admin 落真库
    from gui.main import build_window
    from gui.pages.home.page import HomePage
    from gui.pages.project.page import ProjectPage

    win = build_window()
    assert win.windowTitle() == "AutoVisionAgent"

    home = [w for w in win.findChildren(HomePage) if isinstance(w, HomePage)][0]
    proj = [w for w in win.findChildren(ProjectPage) if isinstance(w, ProjectPage)][0]

    # 项目打开联动：触发 _refresh_home_stats → 仪表盘计数刷新
    proj_dir = tmp_path / "aproj"
    proj_dir.mkdir()
    _png(proj_dir / "img.png")
    (proj_dir / "model.pt").write_bytes(b"w")
    proj.project_opened.emit(str(proj_dir))
    qapp.processEvents()
    assert home._card_images._value_label.text() == "1"
    assert home._card_models._value_label.text() == "1"

    win.select("train")  # 导航切换 no-crash
    win.select("home")


# ============================== ThumbnailTask（W9 QImage 化） ============================== #
@pytest.mark.unit
def test_thumbnail_task_loaded_and_failed(qapp, tmp_path):
    from PySide6.QtGui import QImage

    from gui.widgets.thumbnail_loader import ThumbnailTask

    img = tmp_path / "t.png"
    _png(img, w=40, h=20)

    results, failures = [], []
    task = ThumbnailTask(str(img), size=32)
    task.signals.loaded.connect(lambda p, im: results.append((p, im)))
    task.signals.failed.connect(failures.append)
    task.run()  # 主线程直调（QImage 本身线程安全，测试不必起池）

    assert len(results) == 1
    path, image = results[0]
    assert path == str(img)
    assert isinstance(image, QImage) and not image.isNull()
    assert image.width() == 32  # 缩放生效（40x20 → 32x16 保比例）
    assert failures == []

    bad = ThumbnailTask(str(tmp_path / "missing.png"))
    bad.signals.failed.connect(failures.append)
    bad.run()
    assert failures == [str(tmp_path / "missing.png")]
