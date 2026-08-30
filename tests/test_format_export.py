"""dataset/format_export 单元测试（W5-T2，LabelMe→YOLO/COCO 训练集导出）。

契约：矩形→YOLO 检测行（归一化 cx/cy/w/h）、多边形→分割行、类别名稳定排序、
data.yaml/COCO 结构、坏 JSON 跳过计数、sv.DetectionDataset 回读闭环（计数与
类别一致——supervision 方法文章的狗粮验证）。
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
sv = pytest.importorskip("supervision")

from dataset.format_export import (  # noqa: E402
    labelme_dir_to_coco,
    labelme_dir_to_yolo,
)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _png(path, w=64, h=48):
    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())
    return str(path)


def _labelme(path, image_name, w, h, shapes):
    path.write_text(
        json.dumps(
            {
                "version": "5.4.3",
                "imagePath": image_name,
                "imageHeight": h,
                "imageWidth": w,
                "shapes": shapes,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def fixture_dir(tmp_path):
    """两图（矩形 crack / 多边形 scratch）+ 一个坏 JSON。"""
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    _png(img_dir / "a.png", 64, 48)
    _png(img_dir / "b.png", 64, 48)
    _labelme(
        ann_dir / "a.json", "a.png", 64, 48,
        [{"label": "crack", "shape_type": "rectangle",
          "points": [[10.0, 10.0], [40.0, 30.0]], "group_id": None, "flags": {}}],
    )
    _labelme(
        ann_dir / "b.json", "b.png", 64, 48,
        [{"label": "scratch", "shape_type": "polygon",
          "points": [[5.0, 5.0], [30.0, 5.0], [30.0, 25.0], [5.0, 25.0]],
          "group_id": None, "flags": {}}],
    )
    (ann_dir / "bad.json").write_text("{not json", encoding="utf-8")
    return img_dir, ann_dir


# ----------------------------- YOLO ----------------------------- #
@pytest.mark.unit
def test_yolo_rectangle_line_values(fixture_dir, tmp_path):
    img_dir, ann_dir = fixture_dir
    out = tmp_path / "yolo"
    summary = labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out))

    # 类别稳定排序：crack=0, scratch=1
    assert list(summary.classes) == ["crack", "scratch"]
    assert summary.images == 2 and summary.skipped == 1

    lines = (out / "labels" / "a.txt").read_text().split()
    cls, cx, cy, w, h = int(lines[0]), *(
        float(v) for v in lines[1:5]
    )
    assert cls == 0
    assert cx == pytest.approx(25 / 64)   # (10+40)/2 / 64
    assert cy == pytest.approx(20 / 48)   # (10+30)/2 / 48
    assert w == pytest.approx(30 / 64)
    assert h == pytest.approx(20 / 48)

    # 图像复制到 images/
    assert (out / "images" / "a.png").exists()


@pytest.mark.unit
def test_yolo_polygon_segmentation_line(fixture_dir, tmp_path):
    img_dir, ann_dir = fixture_dir
    out = tmp_path / "yolo"
    labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out))

    parts = (out / "labels" / "b.txt").read_text().split()
    assert int(parts[0]) == 1  # scratch
    coords = [float(v) for v in parts[1:]]
    assert len(coords) == 8  # 4 点 × (x, y) 归一化
    assert coords[0] == pytest.approx(5 / 64, abs=1e-5)
    assert coords[1] == pytest.approx(5 / 48, abs=1e-5)


@pytest.mark.unit
def test_yolo_data_yaml(fixture_dir, tmp_path):
    import yaml

    img_dir, ann_dir = fixture_dir
    out = tmp_path / "yolo"
    labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out))
    data = yaml.safe_load((out / "data.yaml").read_text(encoding="utf-8"))
    assert data["names"] == {0: "crack", 1: "scratch"}
    assert data["nc"] == 2


@pytest.mark.unit
def test_yolo_roundtrip_via_supervision(fixture_dir, tmp_path):
    """狗粮闭环：导出产物由 sv.DetectionDataset.from_yolo 回读。"""
    img_dir, ann_dir = fixture_dir
    out = tmp_path / "yolo"
    labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out))

    ds = sv.DetectionDataset.from_yolo(
        images_directory_path=str(out / "images"),
        annotations_directory_path=str(out / "labels"),
        data_yaml_path=str(out / "data.yaml"),
    )
    assert len(ds) == 2
    assert list(ds.classes) == ["crack", "scratch"]
    # 回读后 a.png 恰有 1 个 crack 框（sv 的 ds[i] 返回 (路径, 图, 检测) 元组）
    idx = list(ds.image_paths).index(str(out / "images" / "a.png"))
    det_a = ds[idx][-1]
    assert len(det_a) == 1 and det_a.class_id[0] == 0


# ----------------------------- COCO ----------------------------- #
@pytest.mark.unit
def test_coco_structure(fixture_dir, tmp_path):
    img_dir, ann_dir = fixture_dir
    out_json = tmp_path / "coco" / "annotations.json"
    summary = labelme_dir_to_coco(str(img_dir), str(ann_dir), str(out_json))

    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert [c["name"] for c in doc["categories"]] == ["crack", "scratch"]
    assert len(doc["images"]) == 2
    assert summary.images == 2 and summary.labels == 2 and summary.skipped == 1

    rect_ann = next(
        a for a in doc["annotations"]
        if doc["categories"][a["category_id"] - 1]["name"] == "crack"
    )
    assert rect_ann["bbox"] == [10.0, 10.0, 30.0, 20.0]  # xywh 绝对坐标
    assert rect_ann["iscrowd"] == 0

    poly_ann = next(
        a for a in doc["annotations"]
        if doc["categories"][a["category_id"] - 1]["name"] == "scratch"
    )
    assert poly_ann["segmentation"] == [[5.0, 5.0, 30.0, 5.0, 30.0, 25.0, 5.0, 25.0]]


@pytest.mark.unit
def test_coco_roundtrip_via_supervision(fixture_dir, tmp_path):
    img_dir, ann_dir = fixture_dir
    out_json = tmp_path / "coco" / "annotations.json"
    labelme_dir_to_coco(str(img_dir), str(ann_dir), str(out_json))

    ds = sv.DetectionDataset.from_coco(
        images_directory_path=str(img_dir),
        annotations_path=str(out_json),
    )
    assert len(ds) == 2
    assert list(ds.classes) == ["crack", "scratch"]


# ----------------------------- GUI 接线（worker 线程） ----------------------------- #
@pytest.mark.unit
def test_data_manage_export_runs_in_worker(qapp, tmp_path, monkeypatch):
    """导出经 threading.Thread 分发（W3 模式），完成后产物落地、按钮恢复。"""
    import threading as _threading

    from PySide6.QtWidgets import QApplication

    img_dir, ann_dir = _make_fixture(tmp_path)
    out_root = tmp_path / "export_out"
    out_root.mkdir()

    from gui.pages.data_manage import page as dm_page_mod

    monkeypatch.setattr(
        dm_page_mod, "pick_directory", lambda *a, **k: str(out_root)
    )
    page = dm_page_mod.DataManagePage()
    page._image_dir = str(img_dir)
    page._annotations_dir = str(ann_dir)

    class _FakeThread:
        created = []

        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._t, self._a, self._k = target, args, kwargs or {}
            _FakeThread.created.append(self)

        def start(self):
            if self._t:
                self._t(*self._a, **self._k)

    monkeypatch.setattr(_threading, "Thread", _FakeThread)
    page._tool_export_dataset()

    assert len(_FakeThread.created) == 1, "导出必须在 worker 线程执行"
    QApplication.processEvents()
    assert page.btn_export.isEnabled()
    assert (out_root / "yolo" / "data.yaml").exists()
    assert (out_root / "yolo" / "labels" / "a.txt").exists()


def _make_fixture(tmp_path):
    """GUI 测试用最小 fixture（复用模块级 fixture 逻辑）。"""
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir(exist_ok=True)
    ann_dir.mkdir(exist_ok=True)
    _png(img_dir / "a.png", 64, 48)
    _labelme(
        ann_dir / "a.json", "a.png", 64, 48,
        [{"label": "crack", "shape_type": "rectangle",
          "points": [[10.0, 10.0], [40.0, 30.0]], "group_id": None, "flags": {}}],
    )
    return img_dir, ann_dir


# ----------------------------- 错误路径 ----------------------------- #
@pytest.mark.unit
def test_empty_dir_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        labelme_dir_to_yolo(str(empty), str(empty), str(tmp_path / "out"))
