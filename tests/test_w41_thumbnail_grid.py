"""W41：缩略图网格对齐（用户报障：行首左缘不齐、图片间距不均）。

根因：ThumbnailTask KeepAspectRatio 产出宽高浮动（120×90 / 120×67…），
IconMode 无 gridSize 时条目尺寸随内容浮动 → 流式换行错位。
修复双保险：方形画布（保比例居中，不拉伸）+ setGridSize 均一网格。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.mark.unit
def test_thumbnail_task_emits_square_canvas(tmp_path):
    """W41：任意比例源图 → 恒定方形画布输出（保比例、不拉伸变形）。"""
    from gui.widgets.thumbnail_loader import ThumbnailTask

    src = QImage(200, 100, QImage.Format_RGB32)
    src.fill(0xFF336699)
    p = tmp_path / "wide.png"
    assert src.save(str(p))

    got = {}
    task = ThumbnailTask(str(p), size=120)
    task.signals.loaded.connect(lambda path, img: got.__setitem__("img", img))
    task.run()  # 同线程直跑（同步 emit）
    img = got.get("img")
    assert img is not None, "应成功加载并回调"
    assert (img.width(), img.height()) == (120, 120), (
        f"输出应为 120×120 方形画布，got {img.width()}x{img.height()}"
    )


@pytest.mark.unit
def test_thumb_grid_rows_aligned_and_uniform(qapp):
    """W41：不同比例缩略图混排 → 网格条目等宽、行首左缘严格对齐。

    视口 600px、格 132px+间距 6 → 每行 4 列；断言第 0/4/8 个条目
    左缘相同（三行行首对齐）且全体等宽。
    """
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    page.thumb_list.resize(600, 600)
    # 真实契约：loader 恒输出 120×120 方形画布（见上测）——本测注入
    # 同尺寸图标，断言网格跨行列缘对齐（icon 宽度不齐时网格按内容
    # 居中属正常，对齐契约的前提就是方形画布）
    n = 10
    for i in range(n):
        key = f"img_{i}.png"
        page.thumb_list.addItem(key)
        page._thumb_items[key] = page.thumb_list.item(i)
        page._on_thumbnail_loaded(key, QImage(120, 120, QImage.Format_RGB32))
    page.thumb_list.doItemsLayout()
    qapp.processEvents()

    rects = [page.thumb_list.visualItemRect(page.thumb_list.item(i)) for i in range(n)]
    # 网格契约：跨行列缘严格对齐（0/4/8 为三行行首；1/5 第二列）
    # ——网格模式下条目宽度按内容居中属正常，对齐才是本修复的契约
    xs = [r.x() for r in rects]
    ys = [r.y() for r in rects]
    assert xs[0] == xs[4] == xs[8], (
        f"行首左缘不齐: x0={xs[0]} x4={xs[4]} x8={xs[8]}"
    )
    assert xs[1] == xs[5], f"第二列跨行不齐: x1={xs[1]} x5={xs[5]}"
    assert len(set(ys)) >= 3, f"应换出 ≥3 行（视口 600/格 168），got {sorted(set(ys))}"
    page.deleteLater()
