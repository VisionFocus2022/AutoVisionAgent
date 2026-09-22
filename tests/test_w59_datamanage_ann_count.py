"""W59：数据管理同目录 LabelMe JSON 统计修复（RED→GREEN 单测）。

回归背景：极柱真实数据集（1288 对 bmp+json 同目录）在数据管理打开后
「已标注: 0 / 无数据」——`_refresh` 的已标注计数只认 `_annotations_dir`
（annotations/ 子目录或兄弟目录），与 `_get_ann_dir()`「优先
annotations/，否则图像目录」口径分裂；同目录 JSON 形态永远数不到。
另修 `_select_dir` 无 else 重置导致的跨目录旧值残留错计数。
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


@pytest.fixture
def dm_page(qapp):
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    page._thumb_pool.clear()  # 不触发缩略图任务（统计面与缩略图无关）
    yield page
    page._thumb_pool.clear()


def _annotated_count(page) -> str:
    return page.lbl_annotated.text()


# ============================== ① 同目录 JSON（主回归） ============================== #


@pytest.mark.unit
def test_same_dir_jsons_counted(dm_page, tmp_path):
    """JSON 与图片同目录（极柱形态）→ 已标注如实计数（W59 主修复）。"""
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png")
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")

    dm_page._image_dir = str(tmp_path)
    dm_page._annotations_dir = None  # 无 annotations/ 子目录（同目录形态）
    dm_page._refresh()

    assert "2" in _annotated_count(dm_page), (
        f"同目录 2 个 JSON 应计入已标注，实得 '{_annotated_count(dm_page)}'"
    )


# ============================== ② annotations/ 子目录形态不回归 ============================== #


@pytest.mark.unit
def test_annotations_subdir_still_wins(dm_page, tmp_path):
    """images/+annotations/ 分离形态（子目录优先）行为不变。"""
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    _png(img_dir / "a.png")
    for i in range(3):
        (ann_dir / f"{i}.json").write_text("{}", encoding="utf-8")

    dm_page._image_dir = str(img_dir)
    dm_page._annotations_dir = str(ann_dir)
    dm_page._refresh()

    assert "3" in _annotated_count(dm_page)


# ============================== ③ 选择目录旧值残留重置 ============================== #


@pytest.mark.unit
def test_select_dir_resets_stale_annotations_dir(dm_page, tmp_path, monkeypatch):
    """换选无兄弟 annotations/ 的目录时，旧 _annotations_dir 必须重置。

    修复前：无 else 分支——上一个数据集的 annotations/ 残留，新目录的
    已标注数的是旧目录的 JSON（跨数据集错计数）。
    """
    from gui.pages.data_manage import page as dm_mod

    old_ann = tmp_path / "old_annotations"
    old_ann.mkdir()
    (old_ann / "stale.json").write_text("{}", encoding="utf-8")
    dm_page._annotations_dir = str(old_ann)

    new_dir = tmp_path / "new_images"
    new_dir.mkdir()
    _png(new_dir / "a.png")

    monkeypatch.setattr(
        dm_mod, "pick_directory", lambda *a, **k: str(new_dir)
    )
    dm_page._select_dir()

    assert dm_page._annotations_dir is None, (
        "无兄弟 annotations/ 时应重置为 None（走图像目录回退），而非残留旧值"
    )
    assert "0" in _annotated_count(dm_page), "新目录无 JSON → 已标注 0（不数旧目录）"
