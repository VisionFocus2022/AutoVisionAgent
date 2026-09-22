"""W59b：标注页同目录 JSON 识别加载 + 训练页样本统计回显（PRD FR-1/2）。

回归背景：极柱数据集（JSON 与图片同目录）在标注页打开后画布恒空
（_load_by_index 从不加载 {图名}.json，v7 记录在案）；训练页选
data.yaml 后无样本反馈。
"""
from __future__ import annotations

import json
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


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


def _labelme(path, img_name, w, h, n_shapes=2):
    doc = {
        "version": "5.0", "imagePath": img_name,
        "imageHeight": h, "imageWidth": w,
        "shapes": [
            {"label": "YS", "shape_type": "polygon",
             "points": [[5, 5], [15, 5], [15, 15]]}
        ] * n_shapes,
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def label_page(qapp):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    msgs: list[tuple[str, str]] = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    page._thumb_pool.clear()
    yield page
    page._thumb_pool.clear()


def _open_folder(page, monkeypatch, folder):
    from gui.pages.label import page as label_mod

    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(folder))
    page.open_folder()
    page._thumb_pool.waitForDone(3000)


# ============================== FR-1① ● 标记 ============================== #


@pytest.mark.unit
def test_annotated_files_marked_in_list(label_page, monkeypatch, tmp_path):
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png")
    _labelme(tmp_path / "a.json", "a.png", 32, 24)

    _open_folder(label_page, monkeypatch, tmp_path)

    texts = [label_page.file_list.item(i).text()
             for i in range(label_page.file_list.count())]
    assert texts[0].startswith("● "), f"有 JSON 的图应带 ● 前缀: {texts}"
    assert not texts[1].startswith("● "), f"无 JSON 的图不应带标记: {texts}"


# ============================== FR-1② 换图自动载入 ============================== #


@pytest.mark.unit
def test_load_by_index_loads_sibling_json(label_page, monkeypatch, tmp_path):
    _png(tmp_path / "a.png")
    _labelme(tmp_path / "a.json", "a.png", 32, 24, n_shapes=2)
    _open_folder(label_page, monkeypatch, tmp_path)

    label_page._load_by_index(0)

    assert len(label_page.canvas.shapes) == 2, "同名 JSON 的 2 个形状应自动载入画布"
    assert any(t == "已载入" for t, _ in label_page._msgs), "状态栏应提示已载入"


@pytest.mark.unit
def test_no_json_image_stays_empty(label_page, monkeypatch, tmp_path):
    _png(tmp_path / "b.png")
    _open_folder(label_page, monkeypatch, tmp_path)

    label_page._load_by_index(0)

    assert label_page.canvas.shapes == []
    assert not any(t == "载入标注失败" for t, _ in label_page._msgs)


@pytest.mark.unit
def test_nonempty_canvas_not_overwritten(label_page, monkeypatch, tmp_path):
    """手绘在途（画布非空）不合并不覆盖——切到已标注图也不动既有手绘。"""
    from labeling.base import AnnotationMode

    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png")
    _labelme(tmp_path / "b.json", "b.png", 32, 24, n_shapes=3)
    _open_folder(label_page, monkeypatch, tmp_path)
    label_page._load_by_index(0)
    label_page.canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, points=[(1, 1), (10, 10)]
    )
    assert len(label_page.canvas.shapes) == 1

    label_page._load_by_index(1)  # 切到 b（W55 清空后手绘已无——回 a 前先验证 b 载入）
    assert len(label_page.canvas.shapes) == 3, "b 的 JSON 应载入"

    label_page.canvas.add_shape(
        mode=AnnotationMode.RECTANGLE, points=[(2, 2), (12, 12)]
    )
    # 直调守卫（换图流程恒先 W55 清空，非空保护为防御性第二道）
    label_page._try_load_existing_json()
    assert len(label_page.canvas.shapes) == 4, "画布非空时不得重载/覆盖"


@pytest.mark.unit
def test_corrupt_json_tolerated(label_page, monkeypatch, tmp_path):
    _png(tmp_path / "c.png")
    (tmp_path / "c.json").write_text("{not valid json", encoding="utf-8")
    _open_folder(label_page, monkeypatch, tmp_path)

    label_page._load_by_index(0)

    assert label_page.canvas.shapes == []
    assert any(t == "载入标注失败" for t, _ in label_page._msgs), "坏 JSON 须诚实提示"


# ============================== FR-2 训练页样本回显 ============================== #


@pytest.mark.unit
def test_train_page_dataset_stats_echo(qapp, tmp_path, monkeypatch):
    from gui.pages.train import page as train_mod

    img_dir = tmp_path / "yolo"
    for split, n in (("train", 2), ("val", 1)):
        (img_dir / split).mkdir(parents=True)
        for i in range(n):
            _png(img_dir / split / f"{i}.png")
    (img_dir / "data.yaml").write_text(
        "train: train\nval: val\n", encoding="utf-8"
    )

    page = train_mod.TrainPage()
    msgs: list[tuple[str, str]] = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))

    import gui.widgets.file_dialog as fd_mod
    monkeypatch.setattr(
        fd_mod, "pick_open_file", lambda *a, **k: str(tmp_path / "yolo" / "data.yaml")
    )
    # 无 yaml 文件也可——回显只依赖路径与目录
    page._browse_data_yaml()

    echo = [a for t, a in msgs if t == "数据集"]
    assert echo and "train=2" in echo[-1] and "val=1" in echo[-1], (
        f"应回显 train/val 计数: {msgs}"
    )


@pytest.mark.unit
def test_train_page_bad_yaml_echo(qapp, tmp_path, monkeypatch):
    from gui.pages.train import page as train_mod

    empty_root = tmp_path / "nothing"
    empty_root.mkdir()
    page = train_mod.TrainPage()
    msgs: list[tuple[str, str]] = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    import gui.widgets.file_dialog as fd_mod

    monkeypatch.setattr(
        fd_mod, "pick_open_file",
        lambda *a, **k: str(empty_root / "ghost.yaml"),
    )
    page._browse_data_yaml()

    assert any("读取失败" in a or "读取失败" in t for t, a in msgs), (
        f"坏清单应诚实提示: {msgs}"
    )
