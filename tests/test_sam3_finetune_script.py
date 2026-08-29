"""finetune_sam3.py 纯函数层单测（W48 · TDD）。

覆盖 scripts/finetune_sam3.py 的无权重纯函数：缺陷形状提取/切分确定性/
盒抖动/多边形栅格化/坐标缩放/匈牙利匹配/分割损失序关系。
GPU/权重相关路径由 --smoke 真机验证（非 pytest 面）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import torch

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "finetune_sam3.py"
_spec = importlib.util.spec_from_file_location("finetune_sam3", _SCRIPT)
ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft)


def _write_labelme(tmp_path: Path, name="img1"):
    pts = [[100, 100], [200, 100], [200, 200], [100, 200]]
    other = [[10, 10], [30, 10], [30, 30], [10, 30]]
    doc = {
        "shapes": [
            {"label": "YS", "shape_type": "polygon", "points": pts},
            {"label": "ZW", "shape_type": "polygon", "points": other},
            {"label": "Z", "shape_type": "polygon", "points": [[0, 0], [5, 0], [5, 5]]},
            {"label": "YS", "shape_type": "rectangle", "points": pts},
        ],
        "imagePath": f"{name}.bmp",
    }
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


class TestExtractDefectShapes:
    def test_only_defect_polygons(self, tmp_path):
        shapes = ft.extract_defect_shapes(_write_labelme(tmp_path))
        # 只收 YS/ZW/TJYS/HS 且 shape_type=polygon（Z 结构标记与 rectangle 剔除）
        assert len(shapes) == 2
        assert all(s.shape[1] == 2 for s in shapes)

    def test_missing_file_returns_empty(self, tmp_path):
        assert ft.extract_defect_shapes(tmp_path / "nope.json") == []


class TestSplit:
    def test_deterministic_and_disjoint(self, tmp_path):
        files = [f"img_{i:03}.bmp" for i in range(50)]
        t1, v1 = ft.split_images(files)
        t2, v2 = ft.split_images(files)
        assert t1 == t2 and v1 == v2
        assert set(t1) & set(v2) == set()
        assert len(t1) + len(v1) == 50
        assert len(v1) == 10

    def test_sorted_input_invariance(self):
        a = ft.split_images(["b", "a", "c", "d", "e", "f", "g", "h", "i", "j"])
        b = ft.split_images(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"])
        assert a == b  # 输入序不改变切分（内部先排序）


class TestJitterBox:
    def test_contains_center_and_inbounds(self):
        rng = np.random.default_rng(7)
        hw = (1000, 1000)
        box = (400, 400, 600, 600)
        for _ in range(50):
            jb = ft.jitter_box(box, hw, rng, frac=0.10)
            x1, y1, x2, y2 = jb
            assert 0 <= x1 < x2 < hw[1] and 0 <= y1 < y2 < hw[0]
            assert x1 <= 500 <= x2 and y1 <= 500 <= y2  # 中心恒在盒内

    def test_tiny_box_min_size(self):
        rng = np.random.default_rng(0)
        for _ in range(20):
            x1, y1, x2, y2 = ft.jitter_box((500, 500, 502, 502), (1000, 1000), rng)
            assert x2 - x1 >= 8 and y2 - y1 >= 8  # 最小盒防退化


class TestRasterizePolygon:
    def test_scale_correct(self):
        # 100:200 正方形，半分辨率 → 50:100
        pts = np.array([[100, 100], [200, 100], [200, 200], [100, 200]], dtype=np.float32)
        m = ft.rasterize_polygon(pts, (100, 100), (0.5, 0.5))
        ys, xs = np.nonzero(m)
        assert m.shape == (100, 100)
        assert 48 <= xs.min() and xs.max() <= 100
        assert 48 <= ys.min() and ys.max() <= 100

    def test_identity_scale(self):
        pts = np.array([[10, 10], [50, 10], [50, 50], [10, 50]], dtype=np.float32)
        m = ft.rasterize_polygon(pts, (64, 64), (1.0, 1.0))
        assert m[10:50, 10:50].all()
        assert m[:5, :].sum() == 0


class TestScaleBox:
    def test_scales_to_target(self):
        out = ft.scale_box((400, 800, 600, 900), (1600, 1600), (1008, 1008))
        assert out == pytest.approx((252.0, 504.0, 378.0, 567.0), abs=0.5)


class TestHungarianSingle:
    def test_picks_min_cost(self):
        cost = np.array([5.0, 1.0, 3.0, 9.0])
        assert ft.hungarian_single(cost) == 1


class TestSegLoss:
    def test_ordering_perfect_vs_empty(self):
        gt = torch.zeros(1, 1, 64, 64)
        gt[0, 0, 16:48, 16:48] = 1.0
        logits = torch.full((1, 1, 64, 64), -8.0)
        loss_bg = ft.focal_dice_loss(logits, gt)
        logits_pos = logits.clone()
        logits_pos[0, 0, 16:48, 16:48] = 8.0
        loss_hit = ft.focal_dice_loss(logits_pos, gt)
        assert loss_hit.item() < loss_bg.item() * 0.5

    def test_finite(self):
        logits = torch.randn(2, 1, 32, 32)
        gt = (torch.rand(2, 1, 32, 32) > 0.5).float()
        assert torch.isfinite(ft.focal_dice_loss(logits, gt))


class TestObjectnessLoss:
    def test_positive_query_dominates(self):
        logits = torch.zeros(200)
        target_idx = 42
        loss = ft.objectness_loss(logits, target_idx)
        logits2 = logits.clone()
        logits2[target_idx] = 6.0
        assert ft.objectness_loss(logits2, target_idx).item() < loss.item()

    def test_bounds(self):
        logits = torch.randn(200)
        assert torch.isfinite(ft.objectness_loss(logits, 7))


class TestFlipAug:
    def test_hflip(self):
        pts = ft.flip_aug(np.array([[10, 5], [90, 5]], dtype=np.float32), (100, 100), horizontal=True)
        assert pts[0][0] == pytest.approx(89, abs=1)  # x' = w-1-x
        assert pts[0][1] == 5
