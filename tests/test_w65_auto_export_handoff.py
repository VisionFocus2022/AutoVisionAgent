"""W65：「下一步：训练」向导自动导出补缺（RED→GREEN）。

回归背景：用户「数据管理全部标注好 → 下一步 → 训练页数据集空」。W63 交接
只在"本会话导出过 YOLO"才有物可带，且 `_last_export_yaml` 纯内存（重启即
丢）——未导出/跨会话两种形态都空交接。

方案 A（用户裁决）：点「下一步：训练」时——
① 本会话导出过且产物在盘 → 直接进训练页（原行为）；
② 有标注未导出 → 自动 YOLO 导出（worker 线程，**无论格式组合框当前选什么
   都强制 YOLO**——训练页只吃 data.yaml）到图像目录兄弟 `_auto_export/yolo`，
   完成后带 data.yaml 自动进训练页；
③ 无标注 → 空交接进训练页（模拟训练诚实回退不变）；
④ 导出失败 → 停在数据管理页报错，pending 清零（不得残留到后续手动导出）。
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
    """经典布局：images/ + annotations/ 各一图一标（矩形）。"""
    img_dir = tmp_path / "proj" / "images"
    ann_dir = tmp_path / "proj" / "annotations"
    img_dir.mkdir(parents=True)
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
    return tmp_path / "proj"


def _record(dm_page):
    got = []
    dm_page.request_page.connect(lambda k: got.append(k))
    return got


# ============================== ① 已导出：直接进 ============================== #

@pytest.mark.unit
def test_goto_train_existing_yaml_navigates(dm_page, tmp_path):
    yaml = tmp_path / "data.yaml"
    yaml.write_text("train: images\n", encoding="utf-8")
    dm_page._last_export_yaml = str(yaml)
    got = _record(dm_page)

    dm_page._goto_train()

    assert got == ["train"], "产物在盘应直接导航"


# ============================== ② 无标注：空交接进（模拟回退不变） ============================== #

@pytest.mark.unit
def test_goto_train_no_annotations_navigates(dm_page):
    got = _record(dm_page)

    dm_page._goto_train()  # 未选任何目录

    assert got == ["train"], "无标注应保持原空交接到航行为"


# ============================== ③ 有标注未导出：自动导出后进 ============================== #

@pytest.mark.unit
def test_goto_train_auto_export_then_navigate(
    dm_page, labeled_proj, fake_threads, qapp
):
    dm_page._image_dir = str(labeled_proj / "images")
    dm_page._annotations_dir = str(labeled_proj / "annotations")
    got = _record(dm_page)

    dm_page._goto_train()
    qapp.processEvents()

    expected_yaml = labeled_proj / "_auto_export" / "yolo" / "data.yaml"
    assert expected_yaml.is_file(), "自动导出应真实产出 data.yaml"
    assert dm_page._last_export_yaml == str(expected_yaml)
    assert got == ["train"], "导出完成后应自动进训练页"
    assert dm_page._auto_nav_pending is False, "导航后 pending 应清零"


@pytest.mark.unit
def test_goto_train_auto_export_forces_yolo(
    dm_page, labeled_proj, fake_threads, qapp
):
    """格式组合框停在 COCO 时自动补缺仍产 YOLO——训练页只吃 data.yaml。"""
    dm_page._image_dir = str(labeled_proj / "images")
    dm_page._annotations_dir = str(labeled_proj / "annotations")
    dm_page.cmb_export_fmt.setCurrentIndex(1)  # COCO
    got = _record(dm_page)

    dm_page._goto_train()
    qapp.processEvents()

    assert (labeled_proj / "_auto_export" / "yolo" / "data.yaml").is_file(), (
        "自动补缺必须强制 YOLO（COCO 无 data.yaml 会空交接）"
    )
    assert got == ["train"]


# ============================== ④ 导出失败：停留+pending 清零 ============================== #

@pytest.mark.unit
def test_goto_train_export_failure_stays(
    dm_page, tmp_path, fake_threads, qapp
):
    """坏标注（无有效 LabelMe）→ 导出 ValueError → 停页报错不导航。"""
    img_dir = tmp_path / "p2" / "images"
    ann_dir = tmp_path / "p2" / "annotations"
    img_dir.mkdir(parents=True)
    ann_dir.mkdir()
    (ann_dir / "broken.json").write_text("{not-json", encoding="utf-8")
    dm_page._image_dir = str(img_dir)
    dm_page._annotations_dir = str(ann_dir)
    got = _record(dm_page)

    dm_page._goto_train()
    qapp.processEvents()

    assert got == [], "导出失败不得导航"
    assert dm_page._auto_nav_pending is False, "失败后 pending 必须清零"
    assert any("失败" in t or "错误" in t for t, _ in dm_page._msgs), (
        f"应有失败状态反馈: {dm_page._msgs}"
    )


# ============================== ⑤ 冻结态权重回退（exe 重打包配套） ============================== #

@pytest.mark.unit
def test_resolve_backbone_frozen_internal(tmp_path, monkeypatch):
    """exe（_MEIPASS=_internal）下裸骨干名命中随包权重——不再触发联网下载。

    CWD 切到空目录模拟重建后的 dist 根（无手拷权重），唯有 _internal 有。"""
    import sys as _sys

    from models.supervised.engines._yolo_seg_base import _resolve_backbone

    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    bundled = tmp_path / "yolov8n-seg.pt"
    bundled.write_bytes(b"w")
    monkeypatch.setattr(_sys, "_MEIPASS", str(tmp_path), raising=False)

    assert _resolve_backbone("yolov8n") == str(bundled)


@pytest.mark.unit
def test_resolve_backbone_cwd_first(tmp_path, monkeypatch):
    """CWD 就近命中优先（W64 手拷 dist 根形态不回归）。"""
    import sys as _sys

    from models.supervised.engines._yolo_seg_base import _resolve_backbone

    monkeypatch.chdir(tmp_path)
    (tmp_path / "yolov8n-seg.pt").write_bytes(b"w")
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "yolov8n-seg.pt").write_bytes(b"bundled")
    monkeypatch.setattr(_sys, "_MEIPASS", str(internal), raising=False)

    assert _resolve_backbone("yolov8n") == "yolov8n-seg.pt"


@pytest.mark.unit
def test_resolve_backbone_pt_passthrough(tmp_path):
    """.pt 路径原样透传（现成权重微调口径，W58 契约不变）。"""
    from models.supervised.engines._yolo_seg_base import _resolve_backbone

    p = tmp_path / "my.pt"
    p.write_bytes(b"w")
    assert _resolve_backbone(str(p)) == str(p)
    # 不存在的裸名也原样返回（交 ultralytics 自行下载/报错——python 模式行为）
    assert _resolve_backbone("yolo11s") == "yolo11s-seg.pt"
