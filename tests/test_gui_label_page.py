"""label 页行为测试（W9-T2：55% → 最大绝对洼地填平）。

文件夹批量加载（递归/上限 500/空目录/坏图）、单图与取消、导航边界、
模式切换与 dragMode、标签应用、撤销重做接线、删除/复制/粘贴、
保存三态 + 自动切下一张（QTimer 真实触发）。
（AI/批量预标注与显隐标注按钮已于 W59 删除——历史用例随特性移除。）
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGraphicsScene,
    QGraphicsView,
    QListWidgetItem,
)

from labeling import AnnotationMode  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


@pytest.fixture
def label_page(qapp):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


@pytest.fixture
def folder3(tmp_path):
    d = tmp_path / "imgs"
    (d / "sub").mkdir(parents=True)
    _png(d / "a.png")
    _png(d / "b.png")
    _png(d / "sub" / "c.png")
    return d


# ============================== 文件夹/单图加载 ============================== #
@pytest.mark.unit
def test_open_folder_loads_first_recursively(label_page, monkeypatch, folder3):
    from gui.pages.label import page as label_mod

    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(folder3))
    label_page.open_folder()
    label_page._thumb_pool.waitForDone(3000)

    assert label_page.file_list.count() == 3
    assert label_page._current_index == 0
    assert label_page.canvas.image_size == (32, 24)
    assert label_page.lbl_pos.text() == "1 / 3"
    assert label_page.btn_prev.isEnabled() is False
    assert label_page.btn_next.isEnabled() is True
    assert any(t == "已加载" for t, _ in label_page._msgs)


@pytest.mark.unit
def test_open_folder_empty_warns(label_page, monkeypatch, tmp_path):
    from gui.pages.label import page as label_mod

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(empty))
    label_page.open_folder()
    assert any(t == "无图像" for t, _ in label_page._msgs)
    assert label_page.file_list.count() == 0


@pytest.mark.unit
def test_open_folder_caps_at_500(label_page, monkeypatch, tmp_path):
    from gui.pages.label import page as label_mod

    d = tmp_path / "many"
    d.mkdir()
    for i in range(501):
        (d / f"{i:03d}.png").write_bytes(b"")  # 空文件即可（不加载内容）
    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(d))
    label_page.open_folder()
    label_page._thumb_pool.waitForDone(5000)
    assert label_page.file_list.count() == 501  # 500 + "更多"提示行
    assert "更多" in label_page.file_list.item(500).text()


@pytest.mark.unit
def test_open_folder_invalid_image_warns(label_page, monkeypatch, tmp_path):
    from gui.pages.label import page as label_mod

    d = tmp_path / "bad"
    d.mkdir()
    (d / "x.png").write_bytes(b"not-an-image")
    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(d))
    label_page.open_folder()
    assert any("失败" in t for t, _ in label_page._msgs)


@pytest.mark.unit
def test_open_image_single_and_cancel(label_page, monkeypatch, folder3):
    from gui.pages.label import page as label_mod

    img = str(folder3 / "a.png")
    monkeypatch.setattr(label_mod, "pick_open_file", lambda *a, **k: img)
    label_page.open_image()
    assert label_page.file_list.count() == 1
    assert label_page._current_index == 0

    # 取消（空路径）：状态不变
    n_msgs = len(label_page._msgs)
    monkeypatch.setattr(label_mod, "pick_open_file", lambda *a, **k: "")
    label_page.open_image()
    assert label_page.file_list.count() == 1
    assert len(label_page._msgs) == n_msgs


# ============================== 导航 ============================== #
@pytest.mark.unit
def test_prev_next_boundaries(label_page, monkeypatch, folder3):
    from gui.pages.label import page as label_mod

    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(folder3))
    label_page.open_folder()

    label_page.next_image()
    assert label_page.lbl_pos.text() == "2 / 3"
    label_page.next_image()
    assert label_page.lbl_pos.text() == "3 / 3"
    assert label_page.btn_next.isEnabled() is False
    label_page.next_image()  # 末尾 no-op
    assert label_page.lbl_pos.text() == "3 / 3"

    label_page.prev_image()
    assert label_page.lbl_pos.text() == "2 / 3"
    label_page.prev_image()
    label_page.prev_image()  # 首张 no-op
    assert label_page.lbl_pos.text() == "1 / 3"
    assert label_page.btn_prev.isEnabled() is False


# ============================== 模式与标签 ============================== #
@pytest.mark.unit
def test_apply_mode_buttons_dragmode_and_sam_warning(label_page, monkeypatch):

    label_page._apply_mode(AnnotationMode.RECTANGLE)
    assert label_page.controller._mode is AnnotationMode.RECTANGLE
    assert label_page._mode_btns[AnnotationMode.RECTANGLE].property("active") is True
    assert label_page.view.dragMode() == QGraphicsView.NoDrag  # 绘制模式禁平移

    label_page._apply_mode(AnnotationMode.POLYGON)
    assert label_page._mode_btns[AnnotationMode.POLYGON].property("active") is True
    # W43：多边形同样 NoDrag + 箭头光标——controller 接管事件流后基类平移
    # 从不触发，ScrollHandDrag 只剩强制手型光标的副作用
    assert label_page.view.dragMode() == QGraphicsView.NoDrag
    assert label_page.view.viewport().cursor().shape() == Qt.ArrowCursor

    # INTERACTIVE 且未选权重：诚实警告（必须屏蔽原生对话框，offscreen 会阻塞）
    # W27：_ensure_sam 自 page.py 抽出至 sam_session.py——对话框 monkeypatch
    # 缝随代码迁移（patch 页模块名不再拦截 Mixin 内解析），断言不变
    from gui.pages.label import sam_session as sam_mod
    monkeypatch.setattr(sam_mod, "pick_open_file", lambda *a, **k: "")
    label_page._msgs.clear()
    label_page._apply_mode(AnnotationMode.INTERACTIVE)
    assert any("SAM" in t for t, _ in label_page._msgs)


@pytest.mark.unit
def test_wheel_zoom_anchors_at_mouse_position(qapp):
    """W43：Ctrl+滚轮缩放以鼠标指向的场景点为锚点，普通滚轮不缩放。

    RED：原实现 scale() 绕视图中心缩放——鼠标下的场景点随缩放漂移，
    放大后目标区域跑出视野，标注员需要反复找回调平位置。
    """
    from gui.pages.label.page import _ZoomableView

    view = _ZoomableView()
    scene = QGraphicsScene()
    scene.setSceneRect(0.0, 0.0, 2000.0, 1500.0)
    view.setScene(scene)
    view.resize(400, 300)
    view.show()
    qapp.processEvents()

    def wheel(x: float, y: float, delta_y: int, ctrl: bool = True):
        view.wheelEvent(QWheelEvent(
            QPointF(x, y), QPointF(10_000, 10_000),
            QPoint(0, 0), QPoint(0, delta_y),
            Qt.NoButton,
            Qt.ControlModifier if ctrl else Qt.NoModifier,
            Qt.NoScrollPhase, False,
        ))

    # 放大：锚点下的场景点缩放后仍在锚点下（滚动条整数值 → ±1 容差）
    pos = QPoint(120, 80)
    before = view.mapToScene(pos)
    wheel(120, 80, 120)
    after = view.mapToScene(pos)
    assert view.transform().m11() == pytest.approx(1.15, rel=1e-9)
    assert (after.x(), after.y()) == pytest.approx(
        (before.x(), before.y()), abs=1.0
    )

    # 缩小回 1.0：反向同样锚定
    pos2 = QPoint(260, 220)
    before2 = view.mapToScene(pos2)
    wheel(260, 220, -120)
    after2 = view.mapToScene(pos2)
    assert view.transform().m11() == pytest.approx(1.0, rel=1e-9)
    assert (after2.x(), after2.y()) == pytest.approx(
        (before2.x(), before2.y()), abs=1.0
    )

    # 普通滚轮（无 Ctrl）交给基类滚动，不改变缩放
    m11 = view.transform().m11()
    wheel(120, 80, 120, ctrl=False)
    assert view.transform().m11() == pytest.approx(m11, rel=1e-9)


@pytest.mark.unit
def test_apply_label_syncs_controller(label_page):
    label_page.label_input.setText("crack")
    label_page._apply_label()
    assert label_page.controller._label == "crack"

    label_page.label_input.setText("   ")  # 空白回退默认
    label_page._apply_label()
    assert label_page.controller._label == "defect"


# ============================== 形状操作 ============================== #
def _add_rect(page, label="defect"):
    page.canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, label=label,
        points=[(1.0, 1.0), (5.0, 5.0)],
    )


@pytest.mark.unit
def test_undo_redo_buttons_wired(label_page):
    _add_rect(label_page)
    _add_rect(label_page, label="b")
    assert label_page.shape_list.count() == 2
    assert label_page.btn_undo.isEnabled() is True

    label_page.btn_undo.click()
    assert len(label_page.canvas.shapes) == 1
    assert label_page.btn_redo.isEnabled() is True
    label_page.btn_redo.click()
    assert len(label_page.canvas.shapes) == 2


@pytest.mark.unit
def test_delete_selected_removes_row(label_page):
    _add_rect(label_page, label="a")
    _add_rect(label_page, label="b")
    label_page.shape_list.setCurrentRow(0)
    label_page._delete_selected()
    assert len(label_page.canvas.shapes) == 1
    assert label_page.canvas.shapes[0].label == "b"


@pytest.mark.unit
def test_copy_paste_with_offset_and_empty_clipboard(label_page):
    _add_rect(label_page, label="a")
    _add_rect(label_page, label="b")

    label_page.shape_list.setCurrentRow(0)
    label_page._copy_shapes()
    assert len(label_page._clipboard) == 1
    assert any(t == "已复制" for t, _ in label_page._msgs)

    label_page._paste_shapes(20)
    assert len(label_page.canvas.shapes) == 3
    pasted = label_page.canvas.shapes[2]
    assert pasted.points[0] == pytest.approx((21.0, 21.0))  # 偏移生效
    assert any(t == "已粘贴" for t, _ in label_page._msgs)

    # 未选中 → 复制全部
    label_page.shape_list.setCurrentRow(-1)
    label_page._copy_shapes()
    assert len(label_page._clipboard) == 3

    fresh = label_page._clipboard
    label_page._clipboard = []
    label_page._paste_shapes()
    assert any("剪贴板为空" in t for t, _ in label_page._msgs)
    label_page._clipboard = fresh


# ============================== 保存 ============================== #
@pytest.mark.unit
def test_save_writes_json_and_auto_advances(label_page, monkeypatch,
                                            folder3, qapp):
    from gui.pages.label import page as label_mod

    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(folder3))
    label_page.open_folder()
    _add_rect(label_page, label="crack")

    out = folder3 / "a.json"
    monkeypatch.setattr(label_mod, "pick_save_file", lambda *a, **k: str(out))
    label_page.save()
    assert any(t == "已保存" for t, _ in label_page._msgs)
    doc = json.loads(out.read_text("utf-8"))
    assert doc["shapes"][0]["label"] == "crack"

    # 保存后 600ms 自动切下一张（真实定时器触发）
    QTest.qWait(750)
    assert label_page.lbl_pos.text() == "2 / 3"


@pytest.mark.unit
def test_save_empty_and_cancel_and_io_error(label_page, monkeypatch, tmp_path):
    from gui.pages.label import page as label_mod

    label_page.save()  # 无形状
    assert any("标注数" in a for t, a in label_page._msgs)

    _add_rect(label_page)
    monkeypatch.setattr(label_mod, "pick_save_file", lambda *a, **k: "")
    label_page.save()  # 取消
    assert not any(t == "已保存" for t, _ in label_page._msgs)

    bad_dir = tmp_path / "adir"
    bad_dir.mkdir()  # save_labelme 会自建父目录——用"路径是目录"触发真 OSError
    monkeypatch.setattr(label_mod, "pick_save_file", lambda *a, **k: str(bad_dir))
    label_page.save()  # IO 失败显式报错
    assert label_page._msgs[-1][1] == "ERROR"


# ============================== 杂项 ============================== #
@pytest.mark.unit
def test_thumbnail_callback_sets_icon(label_page):
    item = QListWidgetItem("a.png")
    label_page.file_list.addItem(item)
    path = "some/path.png"
    label_page._thumb_items[path] = item
    label_page._on_thumbnail_loaded(path, QImage(8, 8, QImage.Format_RGB32))
    assert not item.icon().isNull()


@pytest.mark.unit
def test_retranslate_refresh_texts(label_page):
    label_page.retranslate()
    assert label_page.btn_open_folder.text() == "打开文件夹"
    assert label_page.btn_save.text() == "保存标注"
