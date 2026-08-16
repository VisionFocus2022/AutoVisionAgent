"""有监督评估指标单测（T-AVA-05 验证）。

覆盖 evaluation/metrics_supervised.py 的三个纯函数 + 聚合入口：
- det_map: 检测 mAP（VOC 式单 IoU 阈值）
- seg_iou: 分割 IoU（二值 + 多类）
- abdet_auroc: 异常检测 AUROC
- evaluate_supervised: 任务自动分发
"""
from __future__ import annotations

import numpy as np
import pytest

from evaluation.metrics_supervised import (
    abdet_auroc,
    det_map,
    evaluate_supervised,
    seg_iou,
)


# ============================== det mAP ============================== #
class TestDetMap:
    """检测 mAP 测试。"""

    def test_perfect_prediction(self):
        """完美预测 → mAP = 1.0。"""
        box = [10.0, 10.0, 50.0, 50.0]
        preds = [{"boxes": [box], "scores": [0.95], "labels": [0]}]
        gts = [{"boxes": [box], "labels": [0]}]
        result = det_map(preds, gts, iou_threshold=0.5)
        assert result["mAP"] == pytest.approx(1.0, abs=1e-6)
        assert result["class_0"] == pytest.approx(1.0, abs=1e-6)

    def test_empty_prediction(self):
        """无预测 → mAP = 0.0。"""
        preds = [{"boxes": [], "scores": [], "labels": []}]
        gts = [{"boxes": [[10, 10, 50, 50]], "labels": [0]}]
        result = det_map(preds, gts)
        assert result["mAP"] == 0.0

    def test_partial_match(self):
        """两个 GT，一个命中一个未命中 → mAP ≈ 0.5。"""
        preds = [{
            "boxes": [[10, 10, 50, 50]],
            "scores": [0.9],
            "labels": [0],
        }]
        gts = [{
            "boxes": [[10, 10, 50, 50], [100, 100, 150, 150]],
            "labels": [0, 0],
        }]
        result = det_map(preds, gts, iou_threshold=0.5)
        assert 0.0 < result["mAP"] <= 1.0
        assert result["mAP"] == pytest.approx(0.5, abs=0.05)

    def test_no_gt(self):
        """无 GT → mAP = 0.0（安全退化）。"""
        preds = [{"boxes": [[10, 10, 50, 50]], "scores": [0.9], "labels": [0]}]
        gts = [{"boxes": [], "labels": []}]
        result = det_map(preds, gts)
        assert result["mAP"] == 0.0


# ============================== seg IoU ============================== #
class TestSegIoU:
    """分割 IoU 测试。"""

    def test_perfect_overlap(self):
        """完全重合 → IoU = 1.0。"""
        mask = np.zeros((64, 64), dtype=np.int32)
        mask[20:40, 20:40] = 1
        result = seg_iou(mask, mask)
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_no_overlap(self):
        """无重合 → IoU = 0.0。"""
        pred = np.zeros((64, 64), dtype=np.int32)
        pred[0:20, 0:20] = 1
        gt = np.zeros((64, 64), dtype=np.int32)
        gt[40:60, 40:60] = 1
        result = seg_iou(pred, gt)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_partial_overlap(self):
        """部分重合 → 0 < IoU < 1。"""
        pred = np.zeros((64, 64), dtype=np.int32)
        pred[0:32, 0:32] = 1
        gt = np.zeros((64, 64), dtype=np.int32)
        gt[16:48, 16:48] = 1
        result = seg_iou(pred, gt)
        assert 0.0 < result < 1.0

    def test_shape_mismatch_raises(self):
        """shape 不一致 → ValueError。"""
        pred = np.zeros((32, 32), dtype=np.int32)
        gt = np.zeros((64, 64), dtype=np.int32)
        with pytest.raises(ValueError, match="shape mismatch"):
            seg_iou(pred, gt)

    def test_all_background(self):
        """全背景（label 0）→ IoU = 0.0。"""
        pred = np.zeros((32, 32), dtype=np.int32)
        gt = np.zeros((32, 32), dtype=np.int32)
        assert seg_iou(pred, gt) == 0.0


# ============================== abdet AUROC ============================== #
class TestAbdetAuroc:
    """异常检测 AUROC 测试。"""

    def test_perfect_separation(self):
        """完美分离（异常分数全高于正常）→ AUROC = 1.0。"""
        scores = [0.1, 0.2, 0.3, 0.8, 0.9, 1.0]
        labels = [0, 0, 0, 1, 1, 1]
        result = abdet_auroc(scores, labels)
        assert result == pytest.approx(1.0, abs=1e-4)

    def test_all_positive(self):
        """全正样本 → AUROC = 0.0（无负样本）。"""
        scores = [0.5, 0.6, 0.7]
        labels = [1, 1, 1]
        result = abdet_auroc(scores, labels)
        assert result == 0.0

    def test_all_negative(self):
        """全负样本 → AUROC = 0.0（无正样本）。"""
        scores = [0.1, 0.2, 0.3]
        labels = [0, 0, 0]
        result = abdet_auroc(scores, labels)
        assert result == 0.0

    def test_mixed_scores(self):
        """部分混淆（异常分数与正常分数有重叠）→ 0 < AUROC < 1。"""
        scores = [0.5, 0.55, 0.3, 0.8]
        labels = [1, 0, 0, 1]
        result = abdet_auroc(scores, labels)
        assert 0.0 < result < 1.0

    def test_insufficient_samples(self):
        """不足 2 个样本 → AUROC = 0.0。"""
        assert abdet_auroc([0.5], [0]) == 0.0


# ============================== evaluate_supervised ============================== #
class TestEvaluateSupervised:
    """聚合分发入口测试。"""

    def test_dispatch_det(self):
        """task='det' → 返回 mAP 字段。"""
        box = [10, 10, 50, 50]
        preds = [{"boxes": [box], "scores": [0.9], "labels": [0]}]
        gts = [{"boxes": [box], "labels": [0]}]
        result = evaluate_supervised("det", preds, gts)
        assert "mAP" in result

    def test_dispatch_seg(self):
        """task='seg' → 返回 mIoU 字段。"""
        mask = np.zeros((32, 32), dtype=np.int32)
        mask[10:20, 10:20] = 1
        result = evaluate_supervised("seg", [mask], [mask])
        assert "mIoU" in result

    def test_dispatch_abdet(self):
        """task='abdet' → 返回 AUROC 字段。"""
        result = evaluate_supervised(
            "abdet",
            [0.1, 0.9],
            [0, 1],
        )
        assert "AUROC" in result

    def test_invalid_task_raises(self):
        """不支持的 task → ValueError。"""
        with pytest.raises(ValueError, match="不支持的任务类型"):
            evaluate_supervised("unknown", [], [])
