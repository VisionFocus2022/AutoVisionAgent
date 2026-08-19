"""data_manage 页行为测试（W9-T3：65% → 洼地填平）。

目录定位（images/annotations 布局与回退）、刷新统计（含 >200 分页）、
worker 基础设施成败两路、划分三闸门 + 确认框、导入、七个标注工具
（QInputDialog 注入）与 YOLO/COCO 导出（真实 format_export 落盘）。
"""
from __future__ import annotations

import json
import os
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t: self._t(*self._a, **self._k)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


@pytest.fixture
def proj(tmp_path):
    """标准项目布局：images/ 2 图 + annotations/ 1 个 LabelMe JSON。"""
    img_dir = tmp_path / "proj" / "images"
    ann_dir = tmp_path / "proj" / "annotations"
    img_dir.mkdir(parents=True)
    ann_dir.mkdir()
    _png(img_dir / "a.png")
    _png(img_dir / "b.png")
    (ann_dir / "a.json").write_text(
        json.dumps({"imagePath": "a.png", "imageWidth": 32, "imageHeight": 24,
                    "shapes": [{"label": "crack", "shape_type": "rectangle",
                                "points": [[4, 4], [20, 16]]}]}),
        encoding="utf-8",
    )
    return tmp_path / "proj"


@pytest.fixture
def dm_page(qapp, proj):
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    page.set_project_dir(str(proj))
    msgs.clear()
    return page


class _FakeInputDialog:
    """QInputDialog 注入：getText/getItem 按脚本队列返回。"""

    texts: list = []
    items: list = []

    @staticmethod
    def getText(parent, title, label):
        return (_FakeInputDialog.texts.pop(0), True) if _FakeInputDialog.texts else ("", False)

    @staticmethod
    def getItem(parent, title, label, items, current=0, editable=True):
        return (_FakeInputDialog.items.pop(0), True) if _FakeInputDialog.items else ("", False)


@pytest.fixture
def scripted_input(monkeypatch):
    _FakeInputDialog.texts = []
    _FakeInputDialog.items = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog", _FakeInputDialog
    )
    return _FakeInputDialog


# ============================== 目录与刷新 ============================== #
@pytest.mark.unit
def test_set_project_dir_layout_and_fallback(qapp, tmp_path):
    from gui.pages.data_manage.page import DataManagePage

    bare = tmp_path / "bare"
    bare.mkdir()
    page = DataManagePage()
    page.set_project_dir(str(bare))  # 无子目录：回退到根目录、无标注目录
    assert page._image_dir == str(bare)
    assert page._annotations_dir is None


@pytest.mark.unit
def test_refresh_stats_and_annotations(dm_page, proj):
    assert dm_page.thumb_list.count() == 2
    assert "2" in dm_page.lbl_total.text()
    assert "1" in dm_page.lbl_annotated.text()  # annotations/ 1 个 json
    assert "1" in dm_page.lbl_unannotated.text()
    assert dm_page.lbl_classes.text() == "无数据"


@pytest.mark.unit
def test_refresh_invalid_dir_shows_placeholder(dm_page):
    dm_page._image_dir = None
    dm_page._annotations_dir = None
    dm_page._refresh()
    assert dm_page.lbl_dir.text() == "未选择"
    assert dm_page.thumb_list.count() == 0


@pytest.mark.unit
def test_refresh_over_200_caps_thumbnails(qapp, tmp_path):
    from gui.pages.data_manage.page import DataManagePage

    d = tmp_path / "many"
    d.mkdir()
    for i in range(201):
        (d / f"{i:03d}.png").write_bytes(b"")
    page = DataManagePage()
    page._image_dir = str(d)
    page._refresh()
    page._thumb_pool.waitForDone(5000)
    assert page.thumb_list.count() == 201  # 200 + "更多"提示行
    assert "更多" in page.thumb_list.item(200).text()


@pytest.mark.unit
def test_refresh_natural_order_after_import(qapp, tmp_path):
    """导入后缩略图顺序：数字名未补零时不得按字典序穿插（W20 修复）。

    回归背景：_refresh 曾用 os.walk 裸收集（零排序），展示序=NTFS 枚举序
    （字典序，"pole_2/pole_10" 显示成 1,10,2… 式穿插）——用户观感即
    "导入后图片展示混乱"。修复后按全路径自然排序（数字块按数值比较）。
    W20-2：顶层有图时子目录图像不进列表（划分副本不与根目录同屏重复），
    以提示行告知隐藏数。
    """
    from gui.pages.data_manage.page import DataManagePage

    d = tmp_path / "imported"
    d.mkdir()
    for name in ("pole_10.png", "pole_2.png", "pole_1.png"):
        (d / name).write_bytes(b"")
    train = d / "train"
    train.mkdir()
    for name in ("c_10.png", "c_2.png", "c_1.png"):
        (train / name).write_bytes(b"")
    page = DataManagePage()
    page._image_dir = str(d)
    page._refresh()
    order = [page.thumb_list.item(i).text()
             for i in range(page.thumb_list.count())]
    assert order[:3] == ["pole_1.png", "pole_2.png", "pole_10.png"], (
        f"顶层缩略图应按自然序展示（数字按数值），实际: {order}"
    )
    assert len(order) == 4 and "3" in order[3] and "隐藏" in order[3], (
        f"train/ 下 3 张副本应折叠为一条隐藏提示行，实际: {order}"
    )


@pytest.mark.unit
def test_refresh_same_index_timestamp_order(qapp, tmp_path):
    """同序号多张：组内按时间戳序（W22；极柱真实命名形态）。

    回归背景：缺陷图命名 ``序号_时间戳+序列``，同序号多张且时间戳数字串
    长短不一（17/18/20 位，尾部序列号数字并入同一段）。全数值比较下
    20 位的 20240611…（≈2e19）大于所有 17 位的 20240613…（≈2e16），
    组内排出 0612,0613,0611 式日期倒跳——W20 修复后"导入后顺序混乱"
    复发的根因。期望语义（用户拍板）：首个数字段（序号）按数值，其后
    数字段（时间戳）按文本=按时间先后。
    """
    from gui.pages.data_manage.page import DataManagePage

    d = tmp_path / "ts"
    d.mkdir()
    for name in (
        "73_20240613152714285GT0M6.bmp",   # 06-13，17 位
        "73_20240612162733115R0I65.bmp",   # 06-12，17 位
        "73_20240611190124144332J4.bmp",   # 06-11，20 位（数值最大→旧序垫底）
        "1_20240611184000400ZK3U7.bmp",
        "10_20240611184001721DINFZ.bmp",
        "2_20240611184000951JGDRJ.bmp",
    ):
        (d / name).write_bytes(b"")
    page = DataManagePage()
    page._image_dir = str(d)
    page._refresh()
    order = [page.thumb_list.item(i).text()
             for i in range(page.thumb_list.count())]
    assert order[:3] == [
        "1_20240611184000400ZK3U7.bmp",
        "2_20240611184000951JGDRJ.bmp",
        "10_20240611184001721DINFZ.bmp",
    ], f"序号仍须按数值序（1<2<10），实际: {order}"
    assert order[3:] == [
        "73_20240611190124144332J4.bmp",
        "73_20240612162733115R0I65.bmp",
        "73_20240613152714285GT0M6.bmp",
    ], f"同序号组内应按时间戳序（06-11→06-12→06-13），实际: {order[3:]}"


@pytest.mark.unit
def test_natural_key_first_numeric_rest_text():
    """_natural_key 排序键契约：目录数值序 + 文件名首段数值其后文本（W22）。"""
    from gui.pages.data_manage.page import _natural_key

    # 其后数字段按文本：20 位 06-11 < 17 位 06-13（时间戳恢复时间序）
    assert _natural_key("E:/d/73_20240611190124144332J4.bmp") < _natural_key(
        "E:/d/73_20240613152714285GT0M6.bmp"
    )
    # 主序号按数值
    assert _natural_key("E:/d/2_20240611184000400A.bmp") < _natural_key(
        "E:/d/10_20240611184001721B.bmp"
    )
    # W20 基线语义不回退：pole_N 数值序
    assert _natural_key("E:/d/pole_2.png") < _natural_key("E:/d/pole_10.png")
    # 目录含数字：目录段仍按数值（批2 < 批10）
    assert _natural_key("E:/批2/a.png") < _natural_key("E:/批10/a.png")


@pytest.mark.unit
def test_refresh_copy_split_no_duplicate_display(qapp, tmp_path):
    """W20-2：复制模式划分后根目录与 train/val/test 副本不得同屏重复。

    场景：根 a.png/b.png + train/a.png + val/b.png（copy 划分产物）。
    期望：只展示顶层活动集 2 张 + 1 条隐藏提示（含计数 2），图像总数
    统计也按 2 计（旧行为翻倍为 4）。
    """
    from gui.pages.data_manage.page import DataManagePage

    d = tmp_path / "splitcopy"
    d.mkdir()
    for name in ("a.png", "b.png"):
        (d / name).write_bytes(b"")
    for sub, name in (("train", "a.png"), ("val", "b.png")):
        s = d / sub
        s.mkdir()
        (s / name).write_bytes(b"")
    page = DataManagePage()
    page._image_dir = str(d)
    page._refresh()
    texts = [page.thumb_list.item(i).text()
             for i in range(page.thumb_list.count())]
    assert texts[:2] == ["a.png", "b.png"], f"顶层活动集应原样展示，实际: {texts}"
    assert len(texts) == 3 and "2" in texts[2] and "隐藏" in texts[2], (
        f"子目录 2 张副本应折叠为一条隐藏提示，实际: {texts}"
    )
    assert "4" not in page.lbl_total.text(), (
        f"图像总数不得把划分副本计入（应 2），实际: {page.lbl_total.text()}"
    )


@pytest.mark.unit
def test_refresh_move_split_shows_grouped_subdirs(qapp, tmp_path):
    """W20-2：顶层无图而子目录有图（move 划分后/预划分数据集）→ 分组展示。

    期望：按"子目录/文件名"相对路径展示（同名文件可区分），自然排序。
    """
    from gui.pages.data_manage.page import DataManagePage

    d = tmp_path / "splitmove"
    d.mkdir()
    for sub, names in (
        ("train", ("c_10.png", "c_2.png")),
        ("val", ("v_1.png",)),
    ):
        s = d / sub
        s.mkdir()
        for n in names:
            (s / n).write_bytes(b"")
    page = DataManagePage()
    page._image_dir = str(d)
    page._refresh()
    texts = [page.thumb_list.item(i).text()
             for i in range(page.thumb_list.count())]
    assert texts == ["train/c_2.png", "train/c_10.png", "val/v_1.png"], (
        f"空顶层应按相对路径分组展示子目录图像（自然序），实际: {texts}"
    )


@pytest.mark.unit
def test_select_dir_detects_sibling_annotations(dm_page, monkeypatch, tmp_path,
                                                 proj):
    from gui.pages.data_manage import page as dm_mod

    monkeypatch.setattr(dm_mod, "pick_directory",
                        lambda *a, **k: str(proj / "images"))
    dm_page._select_dir()
    assert dm_page._image_dir == str(proj / "images")
    assert dm_page._annotations_dir == str(proj / "annotations")
    assert any(t == "已选择目录" for t, _ in dm_page._msgs)


# ============================== worker 基础设施 ============================== #
@pytest.mark.unit
def test_run_worker_success_restores_and_refreshes(dm_page, fake_threads, qapp):
    dm_page.btn_import.setEnabled(False)
    dm_page._run_worker("import", lambda: 3, lambda n: f"{n} 张")
    qapp.processEvents()
    assert dm_page.btn_import.isEnabled() is True
    assert any(t == "导入完成" and a == "3 张" for t, a in dm_page._msgs)


@pytest.mark.unit
def test_run_worker_failure_reports(dm_page, fake_threads, qapp):
    def _boom():
        raise OSError("disk full")

    dm_page._run_worker("split", _boom, lambda x: str(x))
    qapp.processEvents()
    assert any(t == "操作失败" and "disk full" in a for t, a in dm_page._msgs)
    assert dm_page.btn_split.isEnabled() is True


# ============================== 导入与划分 ============================== #
@pytest.mark.unit
def test_import_images_requires_dir_then_copies(
    dm_page, fake_threads, monkeypatch, tmp_path, proj, qapp
):
    from gui.pages.data_manage import page as dm_mod

    dm_page._image_dir = None
    dm_page._import_images()
    assert any("请先选择目录" in t for t, _ in dm_page._msgs)
    dm_page._image_dir = str(proj / "images")  # 恢复被闸门检查清掉的目录

    src = tmp_path / "src"
    src.mkdir()
    _png(src / "new.png")
    monkeypatch.setattr(dm_mod, "pick_directory", lambda *a, **k: str(src))
    dm_page._import_images()
    qapp.processEvents()
    imported = tmp_path / "proj" / "images" / "new.png"
    assert imported.exists()
    assert any(t == "导入完成" for t, _ in dm_page._msgs)


@pytest.mark.unit
def test_split_dataset_gates_and_confirm(
    dm_page, fake_threads, monkeypatch, qapp
):
    from gui.pages.data_manage import page as dm_mod
    from PySide6.QtWidgets import QMessageBox

    # 闸门 2：比例之和 ≠ 1.0
    dm_page.spin_train.setValue(0.5)
    dm_page._split_dataset()
    assert any("比例之和" in t for t, _ in dm_page._msgs)
    dm_page.spin_train.setValue(1.0)
    dm_page.spin_val.setValue(0.0)
    dm_page.spin_test.setValue(0.0)

    # 闸门 3：目录无图像
    orig_dir = dm_page._image_dir
    empty = orig_dir + "_empty"
    os.makedirs(empty, exist_ok=True)
    dm_page._image_dir = empty
    dm_page._split_dataset()
    assert any("无图像可划分" in t for t, _ in dm_page._msgs)
    dm_page._image_dir = orig_dir

    # 确认框选 No → 中止（无 worker）
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No)
    )
    dm_page._split_dataset()
    assert not any(t == "划分完成" for t, _ in dm_page._msgs)

    # 选 Yes → copy 模式全量进 train
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    dm_page._split_dataset()
    qapp.processEvents()
    assert any(t == "划分完成" and a == "T2/V0/T0" for t, a in dm_page._msgs)
    assert (dm_page._image_dir and os.path.isdir(
        os.path.join(dm_page._image_dir, "train")))


# ============================== 标注工具 ============================== #
@pytest.mark.unit
def test_get_ann_dir_missing_warns(dm_page):
    dm_page._image_dir = None
    dm_page._annotations_dir = None
    assert dm_page._get_ann_dir() is None
    assert any("请先选择目录" in t for t, _ in dm_page._msgs)


@pytest.mark.unit
def test_tool_statistics_populates_classes(dm_page, fake_threads, qapp):
    dm_page.btn_stat.setEnabled(False)
    dm_page._tool_statistics()
    qapp.processEvents()
    assert dm_page.btn_stat.isEnabled() is True
    assert "crack" in dm_page.lbl_classes.text()
    assert any(t == "标注统计" for t, _ in dm_page._msgs)


@pytest.mark.unit
def test_tool_statistics_empty_dir(qapp, tmp_path, monkeypatch, fake_threads):
    from gui.pages.data_manage.page import DataManagePage

    empty = tmp_path / "no_ann"
    empty.mkdir()
    page = DataManagePage()
    page._image_dir = str(empty)
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._tool_statistics()
    qapp.processEvents()
    assert any(t == "无标注数据" for t, _ in msgs)


@pytest.mark.unit
def test_tool_replace_and_delete_labels(dm_page, fake_threads,
                                        scripted_input, qapp):
    scripted_input.texts = ["crack", "defect"]
    dm_page._tool_replace_label()
    qapp.processEvents()
    assert any(t == "替换完成" for t, _ in dm_page._msgs)
    ann_json = os.path.join(dm_page._annotations_dir, "a.json")
    doc = json.loads(open(ann_json, encoding="utf-8").read())
    assert doc["shapes"][0]["label"] == "defect"

    scripted_input.texts = ["defect"]
    dm_page._tool_delete_labels()
    qapp.processEvents()
    assert any(t == "删除完成" for t, _ in dm_page._msgs)
    doc = json.loads(open(ann_json, encoding="utf-8").read())
    assert doc["shapes"] == []


@pytest.mark.unit
def test_tool_replace_cancelled(dm_page, scripted_input, fake_threads):
    scripted_input.texts = []  # getText → ("", False) → 取消
    dm_page._tool_replace_label()
    assert not any(t == "替换完成" for t, _ in dm_page._msgs)


@pytest.mark.unit
def test_tool_flip_and_cut(dm_page, fake_threads, scripted_input, qapp, proj):
    scripted_input.items = ["horizontal"]
    dm_page._tool_flip_annotation()
    qapp.processEvents()
    assert any(t == "翻转完成" for t, _ in dm_page._msgs)
    doc = json.loads((proj / "annotations" / "a.json").read_text("utf-8"))
    xs = sorted(p[0] for p in doc["shapes"][0]["points"])
    assert xs == [12.0, 28.0]  # w=32 水平翻转：32-20, 32-4

    scripted_input.texts = ["16x16"]
    dm_page._tool_cut_json()
    qapp.processEvents()
    assert any(t == "切割完成" for t, _ in dm_page._msgs)

    scripted_input.texts = ["bad-format"]
    dm_page._tool_cut_json()
    assert any(t == "格式错误" for t, _ in dm_page._msgs)


# ============================== 训练集导出 ============================== #
@pytest.mark.unit
def test_tool_export_yolo_and_coco(dm_page, fake_threads, monkeypatch,
                                   tmp_path, qapp):
    from gui.pages.data_manage import page as dm_mod

    out_root = tmp_path / "export_out"
    monkeypatch.setattr(dm_mod, "pick_directory",
                        lambda *a, **k: str(out_root))

    dm_page._tool_export_dataset()  # 默认 YOLO
    qapp.processEvents()
    assert (out_root / "yolo").exists()
    assert any(t == "导出完成" and "张" in a for t, a in dm_page._msgs)

    dm_page.cmb_export_fmt.setCurrentIndex(1)  # COCO
    dm_page._tool_export_dataset()
    qapp.processEvents()
    assert (out_root / "coco" / "annotations.json").exists()


# ============================== 杂项 ============================== #
@pytest.mark.unit
def test_on_ratio_changed_no_crash(dm_page):
    dm_page.spin_train.setValue(0.7)
    dm_page._on_ratio_changed()


@pytest.mark.unit
def test_thumbnail_callback_sets_icon(dm_page):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QListWidgetItem

    item = QListWidgetItem("a.png")
    dm_page.thumb_list.addItem(item)
    dm_page._thumb_items["x.png"] = item
    dm_page._on_thumbnail_loaded("x.png", QImage(8, 8, QImage.Format_RGB32))
    assert not item.icon().isNull()


@pytest.mark.unit
def test_retranslate_and_update_stats(dm_page):
    dm_page._update_stats(5, 2, {"crack": 2})
    assert "crack: 2" in dm_page.lbl_classes.text()
    dm_page.retranslate()
    assert dm_page.btn_export.text() == "导出训练集"
