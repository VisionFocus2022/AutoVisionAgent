"""dataset/vision_dataset.py 单元测试（R4-12）。

覆盖：目录扫描配对、标注解析、__getitem__ 返回结构。
W1 变更：读图失败由「静默 None」改为显式 ValueError（P2-5），测试图像
从 4 字节假魔数改为真实 PNG（旧写法依赖旧的静默行为）。
"""
import io
import json

import pytest


def _png_bytes(h: int = 8, w: int = 8) -> bytes:
    """生成一张真实 PNG（可被 imread_unicode 解码）。"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.unit
class TestVisionDataset:
    """VisionDataset 功能测试。"""

    def test_scan_pairs_image_annotation(self, tmp_path):
        """扫描目录，正确配对图像和标注文件。"""
        from dataset.vision_dataset import VisionDataset

        # 创建测试图像和标注
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(_png_bytes())  # JPEG magic bytes

        ann_path = tmp_path / "test.json"
        ann_data = {
            "shapes": [
                {
                    "shape_type": "rectangle",
                    "points": [[10, 20], [100, 200]],
                    "label": "defect",
                }
            ]
        }
        ann_path.write_text(json.dumps(ann_data), encoding="utf-8")

        ds = VisionDataset(str(tmp_path), str(tmp_path))
        assert len(ds) == 1

    def test_scan_no_annotation(self, tmp_path):
        """图像无标注文件时 ann_path 为空字符串。"""
        from dataset.vision_dataset import VisionDataset

        img_path = tmp_path / "no_ann.png"
        img_path.write_bytes(_png_bytes())

        ds = VisionDataset(str(tmp_path), str(tmp_path))
        assert len(ds) == 1
        # __getitem__ 不应崩溃
        item = ds[0]
        assert "image" in item
        assert "annotation" in item

    def test_getitem_returns_dict(self, tmp_path):
        """__getitem__ 返回包含 image/annotation/path 的字典。"""
        from dataset.vision_dataset import VisionDataset

        img_path = tmp_path / "item.jpg"
        img_path.write_bytes(_png_bytes())

        ds = VisionDataset(str(tmp_path), str(tmp_path))
        item = ds[0]
        assert isinstance(item, dict)
        assert "image" in item
        assert "annotation" in item
        assert "path" in item
        assert item["path"] == str(img_path)

    def test_getitem_parses_rectangle_annotation(self, tmp_path):
        """正确解析矩形标注。"""
        from dataset.vision_dataset import VisionDataset

        # 创建图像
        (tmp_path / "rect.jpg").write_bytes(_png_bytes())

        # 创建标注
        ann = {
            "shapes": [
                {
                    "shape_type": "rectangle",
                    "points": [[10, 20], [100, 200]],
                    "label": "crack",
                }
            ]
        }
        (tmp_path / "rect.json").write_text(json.dumps(ann), encoding="utf-8")

        ds = VisionDataset(str(tmp_path), str(tmp_path))
        item = ds[0]
        ann = item["annotation"]
        assert len(ann["boxes"]) == 1
        assert ann["boxes"][0] == [10, 20, 100, 200]
        assert ann["labels"][0] == "crack"

    def test_max_items_limit(self, tmp_path):
        """max_items 限制扫描数量。"""
        from dataset.vision_dataset import VisionDataset

        for i in range(5):
            (tmp_path / f"img_{i}.jpg").write_bytes(_png_bytes())

        ds = VisionDataset(str(tmp_path), str(tmp_path), max_items=3)
        assert len(ds) == 3

    def test_empty_directory(self, tmp_path):
        """空目录 → 0 个样本。"""
        from dataset.vision_dataset import VisionDataset
        ds = VisionDataset(str(tmp_path), str(tmp_path))
        assert len(ds) == 0

    def test_annotation_missing_file(self, tmp_path):
        """标注文件不存在时使用空标注。"""
        from dataset.vision_dataset import VisionDataset

        (tmp_path / "only_img.jpg").write_bytes(_png_bytes())

        ds = VisionDataset(str(tmp_path), str(tmp_path))
        item = ds[0]
        assert item["annotation"]["boxes"] == []

    def test_corrupted_annotation(self, tmp_path):
        """损坏的标注文件不崩溃。"""
        from dataset.vision_dataset import VisionDataset

        (tmp_path / "bad_ann.jpg").write_bytes(_png_bytes())
        (tmp_path / "bad_ann.json").write_text("{invalid json!!!", encoding="utf-8")

        ds = VisionDataset(str(tmp_path), str(tmp_path))
        # 不应崩溃，返回空标注
        item = ds[0]
        assert item["annotation"]["boxes"] == []
