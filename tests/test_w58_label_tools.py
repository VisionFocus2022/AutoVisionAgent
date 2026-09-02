"""W58-B（FR-006 补缺）：标注批量工具的备份/空警示/尺寸统计。

背景（假设修正）：S_Tools 首批三件（统计/替换/删除）在 labeling/batch_tools.py
**已存在**（含原子写+失败保原测试 tests/test_batch_tools_atomic.py）——
PRD 立项时误判为「无」（差距测绘 grep 中文按钮词未命中英文实现名）。
本文件只覆盖 PRD AC-006 相对既有实现的三个缺口：
.bak 改写备份 / 删除致空的日志警示 / 统计尺寸分布（count+面积）。
"""
from __future__ import annotations

import json
import logging

import pytest

from labeling.batch_tools import (
    batch_delete_labels,
    batch_replace_label,
    label_data_statistics,
)


def _write_labelme(path, shapes):
    path.write_text(
        json.dumps({"version": "5.4.3", "flags": {}, "shapes": shapes,
                    "imagePath": "x.jpg", "imageData": None,
                    "imageHeight": 64, "imageWidth": 64}),
        encoding="utf-8",
    )


@pytest.fixture()
def ann_dir(tmp_path):
    _write_labelme(tmp_path / "a.json", [
        {"label": "crack", "points": [[4, 4], [20, 16]],
         "shape_type": "rectangle", "flags": {}},               # 面积 16×12=192
        {"label": "crack", "points": [[0, 0], [10, 0], [0, 10]],
         "shape_type": "polygon", "flags": {}},                 # 鞋带 50
    ])
    _write_labelme(tmp_path / "b.json", [
        {"label": "old", "points": [[0, 0], [8, 0], [8, 8], [0, 8]],
         "shape_type": "polygon", "flags": {}},                 # 鞋带 64
    ])
    return tmp_path


@pytest.mark.unit
def test_replace_creates_bak_with_original(ann_dir):
    """替换改写前生成 .bak（内容=改写前原文）——防误操作回滚通道。"""
    original = (ann_dir / "b.json").read_text(encoding="utf-8")
    assert batch_replace_label(str(ann_dir), "old", "new") == 1

    bak = ann_dir / "b.json.bak"
    assert bak.exists(), "改写后应有 .bak 备份"
    assert bak.read_text(encoding="utf-8") == original
    doc = json.loads((ann_dir / "b.json").read_text(encoding="utf-8"))
    assert doc["shapes"][0]["label"] == "new"


@pytest.mark.unit
def test_delete_empty_shapes_logs_warning(ann_dir, caplog):
    """删除致 shapes=[] 的文件留显式日志警示（结果文件留空但可追溯）。"""
    with caplog.at_level(logging.WARNING, logger="labeling.batch_tools"):
        assert batch_delete_labels(str(ann_dir), ["old"]) == 1
    assert any("shapes 为空" in r.message for r in caplog.records), (
        "删除致空应有 WARNING 警示"
    )
    doc = json.loads((ann_dir / "b.json").read_text(encoding="utf-8"))
    assert doc["shapes"] == []


@pytest.mark.unit
def test_statistics_includes_area_distribution(ann_dir):
    """统计含尺寸分布：count / total_area / avg_area（矩形宽高、多边形鞋带）。"""
    stats = label_data_statistics(str(ann_dir))
    crack = stats["crack"]
    assert crack["count"] == 2
    assert abs(crack["total_area"] - 242.0) < 1e-9   # 192 + 50
    assert abs(crack["avg_area"] - 121.0) < 1e-9

    old = stats["old"]
    assert old["count"] == 1
    assert abs(old["total_area"] - 64.0) < 1e-9
    assert abs(old["avg_area"] - 64.0) < 1e-9


@pytest.mark.unit
def test_backup_failure_skips_rewrite(ann_dir, monkeypatch):
    """备份失败 → 该文件跳过改写（宁可不动，不无备份地改）。"""
    from labeling import batch_tools

    monkeypatch.setattr(batch_tools, "_backup_file", lambda _p: False)
    assert batch_replace_label(str(ann_dir), "old", "new") == 0
    doc = json.loads((ann_dir / "b.json").read_text(encoding="utf-8"))
    assert doc["shapes"][0]["label"] == "old"  # 原文未动


@pytest.mark.unit
def test_statistics_bad_points_do_not_break_run(ann_dir):
    """复核 MEDIUM 修正：坏 points（单元素）按面积 0 计数，不击穿整次统计。"""
    _write_labelme(ann_dir / "bad.json", [
        {"label": "weird", "points": [[1.0]], "shape_type": "polygon",
         "flags": {}},
    ])
    stats = label_data_statistics(str(ann_dir))
    assert stats["weird"]["count"] == 1
    assert stats["weird"]["total_area"] == 0.0
    assert stats["crack"]["count"] == 2  # 其余文件不受连坐
