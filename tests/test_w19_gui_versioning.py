"""W19（v3 第三波 FR-4.2 / AC-4.3）：data_manage 页版本管理入口测试。

offscreen 行为四路：
1. "创建快照"按钮存在并接线；设项目目录后点击 → 后台生成快照目录 + 状态回执；
2. 无项目目录点击 → 诚实提示不崩；
3. 后台失败（元组外异常）→ on_error 兜底复位按钮（W17 纪律）；
4. "版本对比"：不足两个快照 → 提示；≥2 → 最近两快照 diff 摘要 QDialog
   （三类计数 + 各 ≤20 条示例，断言对话框文本要点）。
"""
from __future__ import annotations

import os
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextEdit  # noqa: E402

from project import versioning  # noqa: E402


class FakeThread:
    """同步假线程：start() 即执行（接缝约束见 gui/core/jobs.py docstring）。"""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t:
            self._t(*self._a, **self._k)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def proj(tmp_path):
    """标准项目布局：images/ 2 文件 + annotations/ 1 JSON。"""
    img = tmp_path / "proj" / "images"
    ann = tmp_path / "proj" / "annotations"
    img.mkdir(parents=True)
    ann.mkdir()
    (img / "a.png").write_bytes(b"A" * 64)
    (img / "b.png").write_bytes(b"B" * 64)
    (ann / "a.json").write_text("{}", encoding="utf-8")
    return tmp_path / "proj"


@pytest.fixture
def dm_page(qapp, proj):
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    page.set_project_dir(str(proj))
    page._thumb_pool.waitForDone(5000)
    msgs.clear()
    return page


# ============================== 创建快照（AC-4.3） ============================== #
@pytest.mark.unit
def test_page_has_version_group_buttons(dm_page):
    """工具栏"版本"组：创建快照 / 版本对比两按钮存在且文案正确。"""
    assert dm_page.btn_snapshot.text() == "创建快照"
    assert dm_page.btn_diff.text() == "版本对比"
    assert dm_page._op_buttons.get("snapshot") is dm_page.btn_snapshot


@pytest.mark.unit
def test_snapshot_click_creates_snapshot_and_receipt(
    dm_page, fake_threads, qapp, proj
):
    """设项目目录后点击 → 后台快照目录生成 + "快照完成"状态回执。"""
    dm_page.btn_snapshot.click()
    qapp.processEvents()
    snaps = versioning.list_snapshots(str(proj))
    assert len(snaps) == 1
    assert snaps[0][1] == "manual"
    assert os.path.isfile(os.path.join(snaps[0][0], "manifest.json"))
    assert any(t == "快照完成" for t, _ in dm_page._msgs)
    assert dm_page.btn_snapshot.isEnabled() is True  # 完成后按钮复位


@pytest.mark.unit
def test_snapshot_click_without_project_dir_honest(qapp, tmp_path):
    """未设项目目录点击 → 诚实提示，不崩、不产生快照。"""
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page.btn_snapshot.click()  # _project_dir 为 None
    assert any("请先设置项目目录" in t for t, _ in msgs)


@pytest.mark.unit
def test_snapshot_backend_failure_resets_button_via_on_error(
    dm_page, fake_threads, qapp, monkeypatch
):
    """后台抛元组外异常 → run_job on_error 兜底 → 按钮复位 + "操作失败"。"""

    class _WeirdOpError(Exception):
        pass

    def _boom(*_a, **_k):
        raise _WeirdOpError("engine exploded")

    monkeypatch.setattr(versioning, "create_snapshot", _boom)
    dm_page.btn_snapshot.click()
    qapp.processEvents()
    assert any(t == "操作失败" and "engine exploded" in a for t, a in dm_page._msgs)
    assert dm_page.btn_snapshot.isEnabled() is True


# ============================== 版本对比（AC-4.3） ============================== #
@pytest.mark.unit
def test_version_diff_needs_two_snapshots(dm_page, qapp):
    """不足两个快照 → 诚实提示，不弹对话框。"""
    versioning.create_snapshot(dm_page._project_dir, "only")
    dm_page.btn_diff.click()
    assert any("不足两个" in t for t, _ in dm_page._msgs)
    assert getattr(dm_page, "_diff_dialog", None) is None


@pytest.mark.unit
def test_version_diff_dialog_shows_recent_two(dm_page, qapp, proj):
    """≥2 个快照 → 最近两快照 diff 摘要以 QDialog 展示（计数 + 示例）。"""
    versioning.create_snapshot(str(proj), "s1")
    # 快照后：增 1（新文件）+ 改 1（原子替换，断开硬链）
    (proj / "images" / "c.png").write_bytes(b"C" * 32)
    ann = proj / "annotations" / "a.json"
    tmp = ann.with_name("a.json.tmp")
    tmp.write_text('{"x": 1}', encoding="utf-8")
    os.replace(tmp, ann)
    versioning.create_snapshot(str(proj), "s2")

    dm_page.btn_diff.click()
    dlg = dm_page._diff_dialog
    assert dlg is not None
    assert dlg.windowTitle() == "版本对比"
    view = dlg.findChild(QTextEdit, "diffText")
    assert view is not None
    text = view.toPlainText()
    assert "新增 1" in text and "images/c.png" in text
    assert "变更 1" in text and "annotations/a.json" in text
    assert "删除 0" in text


@pytest.mark.unit
def test_version_diff_text_caps_examples_at_20(dm_page):
    """每类示例 ≤20 条；计数仍显示全量（长清单不撑爆对话框）。"""
    diff = {
        "added": [f"images/{i:03d}.png" for i in range(25)],
        "removed": [],
        "changed": [],
    }
    text = dm_page._version_diff_text(diff)
    assert "新增 25" in text
    assert "images/019.png" in text  # 第 20 条仍展示
    assert "images/020.png" not in text  # 第 21 条起截断


# ============================== retranslate ============================== #
@pytest.mark.unit
def test_retranslate_covers_version_buttons(dm_page):
    dm_page.retranslate()
    assert dm_page.btn_snapshot.text() == "创建快照"
    assert dm_page.btn_diff.text() == "版本对比"
