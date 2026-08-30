"""W28（W26 计划 P1）：设置三死键消化 + workspace 单源接线。

背景（对标审查信任债）：
1. 设置页 6 键中 precision/workspace/cache_dir 三键持久化但零消费：
   - workspace → 新建 project.paths.resolve_base_root() 单源，替换
     gui/pages/project/page.py 与 project/counter.py 两处硬编码，
     并接 predict 批量落盘回退（见 test_w28_predict_hygiene.py）。
   - precision → 删除（虚假能力比缺失更糟；引擎无精度档位概念）。
   - cache_dir → 删除行（defer-with-trigger：离线权重缓存触发时再建）。
2. About 文案仍宣称已删除的零样本范式（W18 起零样本桥已拆）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ws_settings(tmp_path, monkeypatch):
    """把 user_settings.json 指到 tmp（workspace=子目录 ws），返回两路径。"""
    import gui.core.settings_io as settings_io

    ws = tmp_path / "ws"
    (tmp_path / "user_settings.json").write_text(
        json.dumps({"workspace": str(ws)}), encoding="utf-8"
    )
    monkeypatch.setattr(settings_io, "CONFIG_DIR", tmp_path)
    return tmp_path, ws


# ============================== resolve_base_root 单源 ============================== #


@pytest.mark.unit
def test_resolve_base_root_reads_workspace(ws_settings):
    """resolve_base_root：user_settings.workspace 优先，缺省回默认根。"""
    from project.paths import resolve_base_root

    _tmp, ws = ws_settings
    assert resolve_base_root() == str(ws)


@pytest.mark.unit
def test_resolve_base_root_falls_back_to_default(tmp_path, monkeypatch):
    """无 workspace 配置 → core.constants.DEFAULT_PROJECT_ROOT。"""
    import gui.core.settings_io as settings_io
    from core.constants import DEFAULT_PROJECT_ROOT
    from project.paths import resolve_base_root

    monkeypatch.setattr(settings_io, "CONFIG_DIR", tmp_path)  # 空目录无配置
    assert resolve_base_root() == DEFAULT_PROJECT_ROOT


@pytest.mark.unit
def test_resolve_base_root_survives_settings_layer_failure(tmp_path, monkeypatch):
    """settings 层不可导入/抛错不得击穿根目录解析（lite/裁剪环境回退默认）。"""
    import gui.core.settings_io as settings_io
    from core.constants import DEFAULT_PROJECT_ROOT
    from project import paths as paths_mod

    def _boom(config_dir=None):
        raise OSError("disk gone")

    monkeypatch.setattr(settings_io, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(settings_io, "load_user_settings", _boom)
    assert paths_mod.resolve_base_root() == DEFAULT_PROJECT_ROOT


# ============================== 两处硬编码替换 ============================== #


@pytest.mark.unit
def test_counter_default_uses_resolve_base_root(ws_settings):
    """TaskCounter() 默认根走 resolve_base_root（替换原内联 expanduser）。"""
    from project.counter import TaskCounter

    _tmp, ws = ws_settings
    assert TaskCounter()._base_root == str(ws)


@pytest.mark.unit
def test_project_page_base_root_uses_resolve_base_root(qapp, tmp_path, monkeypatch):
    """项目管理页 base_root 走 resolve_base_root（替换原硬编码默认根）。"""
    from gui.pages.project import page as proj_mod
    from gui.pages.project.page import ProjectPage

    monkeypatch.setattr(proj_mod, "resolve_base_root", lambda: str(tmp_path / "ws"))
    page = ProjectPage()
    assert page._base_root == str(tmp_path / "ws")


@pytest.mark.unit
def test_no_inline_default_project_root_duplication():
    """守卫：默认根字面量只许住在 core.constants（两处硬编码不得复发）。"""
    targets = [
        REPO_ROOT / "gui" / "pages" / "project" / "page.py",
        REPO_ROOT / "project" / "counter.py",
    ]
    for t in targets:
        src = t.read_text(encoding="utf-8")
        assert "~/AutoVisionAgent_Projects" not in src, (
            f"{t.name} 含内联默认根——应走 resolve_base_root() 单源"
        )


# ============================== precision / cache_dir 死键删除 ============================== #


@pytest.mark.unit
def test_settings_page_no_dead_precision_and_cache_rows(qapp, tmp_path, monkeypatch):
    """precision/cache_dir 为虚假能力（持久化但零消费）——控件与键一并删除。"""
    from gui.pages.settings import page as settings_mod
    from gui.pages.settings.page import SettingsPage

    monkeypatch.setattr(settings_mod, "_CONFIG_DIR", tmp_path)
    page = SettingsPage()
    assert not hasattr(page, "_precision_combo"), "precision 死键应删除（虚假能力）"
    assert not hasattr(page, "_cache_edit"), "cache_dir 死键应删除（defer-with-trigger）"

    monkeypatch.setattr(
        "gui.widgets.file_dialog.pick_directory",
        lambda *a, **k: str(tmp_path / "ws"),
    )
    page._pick_workspace()
    page._save()
    saved = json.loads((tmp_path / "user_settings.json").read_text("utf-8"))
    assert "precision" not in saved, "保存键不得再含 precision"
    assert "cache_dir" not in saved, "保存键不得再含 cache_dir"
    assert saved.get("workspace", "").endswith("ws")


# ============================== About 文案诚实化 ============================== #


@pytest.mark.unit
def test_about_text_no_zero_shot_claim(qapp):
    """About 删除「零样本 + 有监督双范式」stale 宣称（零样本未实装）。"""
    from gui.pages.settings.page import SettingsPage

    page = SettingsPage()
    texts = " ".join(lbl.text() for lbl in page.findChildren(QLabel))
    assert "零样本" not in texts, "About 不得再宣称零样本范式（W18 起未实装）"
    assert "双范式" not in texts
