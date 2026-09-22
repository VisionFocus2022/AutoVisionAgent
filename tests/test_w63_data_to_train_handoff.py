"""W63：数据管理「下一步：训练」数据集上下文交接（RED→GREEN）。

回归背景：W62 打通标注→数据管理交接后，向导最后一跳仍是断的——数据管理
点「下一步：训练」只切页，刚导出的 YOLO 训练集（data.yaml）不会带入训练页，
训练保持"未选择（模拟训练）"而用户以为在用刚导出的数据。

方案（对称 W62 三件套）：数据管理页导出成功记 `last_dataset_yaml`（仅 YOLO
分支，COCO 无 data.yaml 不记）；训练页加 `apply_external_dataset(yaml)`（填
txt_data+统计回显，无对话框版浏览逻辑）；main.py `_wire_data_to_train_handoff`
接线（空值零操作，不覆盖无导出场景的诚实模拟回退）。
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


def _png(path, w=16, h=12):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


@pytest.fixture
def dm_page(qapp):
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    page._thumb_pool.clear()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    yield page
    page._thumb_pool.clear()


@pytest.fixture
def labeled_proj(tmp_path):
    """可导出的最小标注项目：images/a.png + annotations/a.json（矩形）。"""
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    _png(img_dir / "a.png")
    (ann_dir / "a.json").write_text(
        json.dumps({
            "imagePath": "a.png", "imageWidth": 16, "imageHeight": 12,
            "shapes": [{"label": "crack", "shape_type": "rectangle",
                        "points": [[2, 2], [10, 8]]}],
        }),
        encoding="utf-8",
    )
    return tmp_path


# ============================== ① 导出成功记 data.yaml ============================== #

@pytest.mark.unit
def test_export_yolo_captures_dataset_yaml(
    dm_page, labeled_proj, fake_threads, monkeypatch, qapp
):
    """YOLO 导出成功后 last_dataset_yaml 指向产物 data.yaml（真实落盘）。"""
    from gui.pages.data_manage import page as dm_mod

    out_root = labeled_proj / "export_out"
    monkeypatch.setattr(dm_mod, "pick_directory", lambda *a, **k: str(out_root))
    dm_page._image_dir = str(labeled_proj / "images")
    dm_page._annotations_dir = str(labeled_proj / "annotations")

    dm_page._tool_export_dataset()  # 默认 YOLO
    qapp.processEvents()

    expected = out_root / "yolo" / "data.yaml"
    assert expected.is_file(), "导出应真实产出 data.yaml"
    assert dm_page.last_dataset_yaml == str(expected)


@pytest.mark.unit
def test_export_coco_does_not_capture(dm_page, labeled_proj,
                                      fake_threads, monkeypatch, qapp):
    """COCO 导出无 data.yaml——last_dataset_yaml 保持空（诚实不误交接）。"""
    from gui.pages.data_manage import page as dm_mod

    out_root = labeled_proj / "export_out"
    monkeypatch.setattr(dm_mod, "pick_directory", lambda *a, **k: str(out_root))
    dm_page._image_dir = str(labeled_proj / "images")
    dm_page._annotations_dir = str(labeled_proj / "annotations")
    dm_page.cmb_export_fmt.setCurrentIndex(1)  # COCO

    dm_page._tool_export_dataset()
    qapp.processEvents()

    assert (out_root / "coco" / "annotations.json").exists()
    assert dm_page.last_dataset_yaml == ""


@pytest.mark.unit
def test_last_dataset_yaml_initial_empty(dm_page):
    assert dm_page.last_dataset_yaml == ""


# ============================== ② 训练页 apply_external_dataset ============================== #

@pytest.mark.unit
def test_train_apply_external_dataset(qapp, tmp_path):
    """填入 txt_data 并回显样本统计（train=N val=M）。"""
    from gui.pages.train.page import TrainPage

    (tmp_path / "images").mkdir()
    _png(tmp_path / "images" / "a.png")
    _png(tmp_path / "images" / "b.png")
    yaml_path = tmp_path / "data.yaml"
    yaml_path.write_text(
        "train: images\nval: images\nnc: 1\nnames:\n  0: crack\n",
        encoding="utf-8",
    )

    page = TrainPage()
    got = []
    page.status_changed.connect(lambda t, a: got.append((t, a)))

    page.apply_external_dataset(str(yaml_path))

    assert page.txt_data.text() == str(yaml_path)
    assert any(t == "数据集" and "train=2" in a and "val=2" in a
               for t, a in got), f"统计未回显: {got}"


# ============================== ③ build_window 向导接线 ============================== #

@pytest.mark.unit
def test_build_window_handoff_data_to_train(qapp, tmp_path, monkeypatch):
    """数据管理 emit request_page("train") → 训练页自动带入 data.yaml。"""
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path / "cfg")
    (tmp_path / "cfg").mkdir()
    from gui.main import build_window
    from gui.pages.data_manage.page import DataManagePage
    from gui.pages.train.page import TrainPage

    win = build_window()
    win.set_role("admin")  # train 页需 admin+（operator 不可见）
    data = [w for w in win.findChildren(DataManagePage)][0]
    train = [w for w in win.findChildren(TrainPage)][0]

    yaml_path = tmp_path / "data.yaml"
    yaml_path.write_text("train: images\nval: images\n", encoding="utf-8")
    data._last_export_yaml = str(yaml_path)
    data.request_page.emit("train")
    qapp.processEvents()

    assert train.txt_data.text() == str(yaml_path), (
        "向导切页应把最近导出的 data.yaml 带入训练页"
    )


@pytest.mark.unit
def test_build_window_handoff_no_export_noop(qapp, tmp_path, monkeypatch):
    """未导出过（last_dataset_yaml 空）→ 不覆盖训练页既有选择。"""
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path / "cfg")
    (tmp_path / "cfg").mkdir()
    from gui.main import build_window
    from gui.pages.data_manage.page import DataManagePage
    from gui.pages.train.page import TrainPage

    win = build_window()
    win.set_role("admin")
    data = [w for w in win.findChildren(DataManagePage)][0]
    train = [w for w in win.findChildren(TrainPage)][0]

    keep = tmp_path / "keep.yaml"
    keep.write_text("train: images\n", encoding="utf-8")
    train.txt_data.setText(str(keep))
    data.request_page.emit("train")
    qapp.processEvents()

    assert train.txt_data.text() == str(keep), "空交接应零操作"
