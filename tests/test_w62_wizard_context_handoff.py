"""W62：标注页「下一步：数据管理」目录上下文交接（RED→GREEN）。

回归背景：W59c 向导 request_page 只切页不带上下文——标注页打开并标注完
文件夹后点「下一步」，数据管理页仍是空的（需手动重选目录）。

方案（沿 main.py 既有页间交接先例 project_opened→set_project_dir）：
① 标注页保存并暴露 current_folder；
② 数据管理页从 _select_dir 抽出 apply_external_dir（同语义无对话框）；
③ build_window 接 _handoff_label_to_data（仅 key=="data_manage" 且
   current_folder 非空时交接；空文件夹零操作，不碰用户已选目录）。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _png(path, w=16, h=12):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


# ============================== ① 标注页 current_folder ============================== #

@pytest.mark.unit
def test_label_current_folder_property(qapp, tmp_path, monkeypatch):
    """open_folder 后 current_folder 返回所开目录；未打开时为空串。"""
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    assert page.current_folder == "", "未打开文件夹时应为空串"

    folder = tmp_path / "imgs"
    folder.mkdir()
    _png(folder / "a.png")

    import gui.pages.label.page as label_page_mod

    monkeypatch.setattr(
        label_page_mod, "pick_directory", lambda *a, **k: str(folder)
    )
    page.open_folder()
    assert page.current_folder == str(folder)


@pytest.mark.unit
def test_label_current_folder_single_image(qapp, tmp_path, monkeypatch):
    """open_image（单图）时 current_folder 回落为图片所在目录。"""
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    img = tmp_path / "solo.png"
    _png(img)

    import gui.pages.label.page as label_page_mod

    monkeypatch.setattr(
        label_page_mod, "pick_open_file", lambda *a, **k: str(img)
    )
    page.open_image()
    assert page.current_folder == str(tmp_path)


# ============================== ② 数据管理 apply_external_dir ============================== #

@pytest.mark.unit
def test_apply_external_dir_flat_layout(qapp, tmp_path):
    """平铺形态（极柱：图+同名 JSON 同目录）→ 图像目录就位、缩略图与
    已标注统计即刻可见（W59 同目录口径不回归）。"""
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    page._thumb_pool.clear()
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png")
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")

    page.apply_external_dir(str(tmp_path))

    assert page._image_dir == str(tmp_path)
    assert page._annotations_dir is None
    assert page._get_ann_dir() == str(tmp_path), "W59 回退口径应命中图像目录"
    assert page.thumb_list.count() == 2
    assert "1" in page.lbl_annotated.text()
    page._thumb_pool.clear()


@pytest.mark.unit
def test_apply_external_dir_sibling_annotations(qapp, tmp_path):
    """经典形态（images/ + 兄弟 annotations/）→ annotations 目录命中。"""
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    page._thumb_pool.clear()
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    _png(img_dir / "a.png")
    (ann_dir / "a.json").write_text("{}", encoding="utf-8")

    page.apply_external_dir(str(img_dir))

    assert page._image_dir == str(img_dir)
    assert page._annotations_dir == str(ann_dir)
    assert "1" in page.lbl_annotated.text()
    page._thumb_pool.clear()


# ============================== ③ build_window 向导接线 ============================== #

@pytest.mark.unit
def test_build_window_handoff_label_to_data(qapp, tmp_path, monkeypatch):
    """标注页 emit request_page("data_manage") → 数据管理自动带入目录。"""
    from gui.pages.data_manage.page import DataManagePage
    from gui.pages.label.page import LabelPage
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path / "cfg")
    (tmp_path / "cfg").mkdir()
    from gui.main import build_window

    win = build_window()
    label = [w for w in win.findChildren(LabelPage)][0]
    data = [w for w in win.findChildren(DataManagePage)][0]

    folder = tmp_path / "imgs"
    folder.mkdir()
    _png(folder / "a.png")
    label._folder = str(folder)  # 模拟已在标注页打开文件夹
    label.request_page.emit("data_manage")
    qapp.processEvents()

    assert data._image_dir == str(folder), (
        "向导切页应把标注页文件夹带入数据管理"
    )


@pytest.mark.unit
def test_build_window_handoff_empty_folder_noop(qapp, tmp_path, monkeypatch):
    """标注页未打开文件夹（current_folder 空）→ 不碰数据管理既有目录。"""
    from gui.pages.data_manage.page import DataManagePage
    from gui.pages.label.page import LabelPage
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path / "cfg")
    (tmp_path / "cfg").mkdir()
    from gui.main import build_window

    win = build_window()
    label = [w for w in win.findChildren(LabelPage)][0]
    data = [w for w in win.findChildren(DataManagePage)][0]

    keep = tmp_path / "keep"
    keep.mkdir()
    data._image_dir = str(keep)
    label.request_page.emit("data_manage")
    qapp.processEvents()

    assert data._image_dir == str(keep), "空文件夹交接应为零操作"
