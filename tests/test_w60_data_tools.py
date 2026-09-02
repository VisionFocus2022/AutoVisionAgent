"""W60（FR-008）：S_Tools 工具次批——裁剪数据集（图+标注配对瓦片）/ 照片尾缀
修改 / 数据清洗（坏图隔离）。

评估留档：裁剪数据集存量只有 JSON 切割（cut_annotations→cut_labelme_json），
图像从不切片、瓦片无配对——本批补图像侧；尾缀修改/清洗为零实现。
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _png(path, w=64, h=48):
    import cv2

    ok, buf = cv2.imencode(".png", np.full((h, w, 3), 128, np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


def _labelme(path, image_name, w, h, shapes):
    path.write_text(
        json.dumps({"version": "5.4.3", "imagePath": image_name,
                    "imageHeight": h, "imageWidth": w, "shapes": shapes}),
        encoding="utf-8",
    )


# ============================== 裁剪数据集（配对瓦片） ============================== #


@pytest.mark.unit
def test_crop_dataset_pairs_image_and_json_tiles(tmp_path):
    from labeling.batch_tools import crop_dataset

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    _png(img_dir / "a.png", w=64, h=48)
    _labelme(
        img_dir / "a.json", "a.png", 64, 48,
        [{"label": "crack", "shape_type": "rectangle",
          "points": [[4, 4], [60, 44]], "group_id": None, "flags": {}}],
    )

    tiles_imgs, tiles_jsons = crop_dataset(str(img_dir), tile_w=32, tile_h=24)
    tiles_dir = img_dir / "tiles"
    assert tiles_dir.is_dir()

    # 图像瓦片与 JSON 瓦片成对（同名 stem，图 jpg 对齐 json imagePath 约定）
    img_tiles = {p.name for p in tiles_dir.glob("*.jpg")}
    json_tiles = {p.name for p in tiles_dir.glob("*.json")}
    assert len(img_tiles) >= 4  # 64x48 / 32x24 = 2x2 起
    assert len(json_tiles) >= 1
    for j in json_tiles:
        stem = j.rsplit(".", 1)[0]
        assert f"{stem}.jpg" in img_tiles, f"瓦片 {j} 无配对图像"
        doc = json.loads((tiles_dir / j).read_text(encoding="utf-8"))
        assert doc["imagePath"].startswith(stem)
    assert tiles_imgs >= 0 and tiles_jsons >= 0  # 计数返回形态


@pytest.mark.unit
def test_crop_dataset_image_without_json_still_tiles(tmp_path):
    """无标注的图像也切（纯数据集裁剪场景）。"""
    from labeling.batch_tools import crop_dataset

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    _png(img_dir / "b.png", w=40, h=30)
    imgs, jsons = crop_dataset(str(img_dir), tile_w=32, tile_h=24)
    assert imgs >= 1 and jsons == 0
    assert (img_dir / "tiles").is_dir()


# ============================== 照片尾缀修改 ============================== #


@pytest.mark.unit
def test_rename_image_suffix(tmp_path):
    from labeling.batch_tools import rename_image_suffix

    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    _png(img_dir / "A.JPG")
    _png(img_dir / "B.JPG")
    _png(img_dir / "c.png")
    _labelme(img_dir / "A.json", "A.JPG", 64, 48, [])

    count = rename_image_suffix(str(img_dir), ".JPG", ".jpg")
    assert count == 2
    # NTFS 大小写不敏感：exists() 对任意大小写恒真——用 listdir 实名断言
    names = set(os.listdir(img_dir))
    assert "A.jpg" in names and "A.JPG" not in names
    assert "B.jpg" in names
    assert (img_dir / "c.png").exists()  # 其他后缀不动
    assert (img_dir / "A.json").exists()  # 同名标注不动（stem 未变）


# ============================== 数据清洗 ============================== #


@pytest.mark.unit
def test_clean_dataset_report_only(tmp_path):
    from labeling.batch_tools import clean_dataset

    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    _png(img_dir / "good.png")
    (img_dir / "zero.png").write_bytes(b"")  # 零字节
    (img_dir / "bad.png").write_bytes(b"not-an-image")  # 坏图
    _labelme(img_dir / "good.json", "good.png", 64, 48, [])
    _labelme(img_dir / "orphan.json", "orphan.png", 64, 48, [])  # 孤立标注

    report = clean_dataset(str(img_dir))
    assert report["corrupt"] == 2  # 零字节 + 坏图
    assert report["orphan_json"] == 1
    assert report["moved"] == 0  # 报告模式不动文件
    assert (img_dir / "bad.png").exists()


@pytest.mark.unit
def test_clean_dataset_quarantine_moves(tmp_path):
    from labeling.batch_tools import clean_dataset

    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    _png(img_dir / "good.png")
    (img_dir / "zero.png").write_bytes(b"")
    _labelme(img_dir / "orphan.json", "orphan.png", 64, 48, [])

    report = clean_dataset(str(img_dir), quarantine="_trash")
    assert report["moved"] == 2  # 坏图 + 孤立 json 进隔离目录
    trash = img_dir / "_trash"
    assert (trash / "zero.png").exists()
    assert (trash / "orphan.json").exists()
    assert (img_dir / "good.png").exists()  # 好文件不动
    assert not (img_dir / "zero.png").exists()


# ============================== 页面接线（Mixin） ============================== #


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.unit
def test_data_manage_extra_tool_buttons(qapp):
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    for attr in ("btn_crop_ds", "btn_suffix", "btn_clean"):
        assert hasattr(page, attr), f"{attr} 按钮缺失"
    # 既有三件按钮仍在（Mixin 抽取零破坏）
    for attr in ("btn_stat", "btn_replace", "btn_delete_lbl"):
        assert hasattr(page, attr)
    page.deleteLater()
