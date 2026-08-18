"""有监督任务评估指标（FR-B5，纯函数）。

提供检测 mAP、分割 IoU、异常检测 AUROC 三组纯函数指标，
不依赖 industrial_vision_platform.ModelEvaluator 的模型评估流程
（后者面向 nn.Module + DataLoader），仅消费预测与标注的数值数组。

设计原则：纯函数 + numpy/torch 仅做计算；无副作用；可单测断言。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ============================== IoU ============================== #
def _box_iou(
    box_a: Tuple[float, float, float, float],
    box_b: Tuple[float, float, float, float],
) -> float:
    """计算两个 [x1, y1, x2, y2] 框的 IoU。"""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


# ============================== det mAP ============================== #
def _match_class_detections(
    preds: Sequence[Dict],
    gts: Sequence[Dict],
    cls: int,
    iou_threshold: float,
) -> Tuple[List[float], List[int], int]:
    """单类收集：逐图取当前类预测/标注并做 IoU 匹配。

    返回 ``(all_scores, all_tp, n_gt)``——该类全部预测分数（图序、
    图内按分数降序）、TP/FP 标记（1/0）与该类 GT 总数。
    """
    all_scores: List[float] = []
    all_tp: List[int] = []  # 1=TP, 0=FP
    n_gt = 0

    for pred, gt in zip(preds, gts):
        p_boxes = np.asarray(pred.get("boxes", []))
        p_scores = np.asarray(pred.get("scores", []))
        p_labels = np.asarray(pred.get("labels", []))
        g_boxes = np.asarray(gt.get("boxes", []))
        g_labels = np.asarray(gt.get("labels", []))

        # W17（v3 P1-2）防御：labels/scores 与 boxes 长度失配时按单类 0 /
        # 零分对齐——布尔掩码错配会抛裸 IndexError 击穿调用方 except 元组
        # （上游 eval_flow 已保证一致，此处兜底未来调用方再构造失配输入）。
        if len(p_labels) != len(p_boxes):
            p_labels = np.zeros(len(p_boxes), dtype=np.int64)
        if len(p_scores) != len(p_boxes):
            p_scores = np.zeros(len(p_boxes), dtype=np.float64)

        # 过滤当前类
        p_mask = p_labels == cls if len(p_labels) else np.array([])
        g_mask = g_labels == cls if len(g_labels) else np.array([])

        p_cls = p_boxes[p_mask] if len(p_mask) else np.array([]).reshape(0, 4)
        p_cls_scores = p_scores[p_mask] if len(p_mask) else np.array([])
        g_cls = g_boxes[g_mask] if len(g_mask) else np.array([]).reshape(0, 4)

        n_gt += len(g_cls)
        if len(p_cls) == 0:
            continue

        # 按分数降序排列
        order = np.argsort(-p_cls_scores)
        p_cls = p_cls[order]
        p_cls_scores = p_cls_scores[order]

        # 匹配 GT
        matched = np.zeros(len(g_cls), dtype=bool)
        for i in range(len(p_cls)):
            best_iou = 0.0
            best_j = -1
            for j in range(len(g_cls)):
                if matched[j]:
                    continue
                iou = _box_iou(p_cls[i], g_cls[j])
                if iou > best_iou:
                    best_iou = iou
                    best_j = j
            if best_iou >= iou_threshold and best_j >= 0:
                matched[best_j] = True
                all_tp.append(1)
            else:
                all_tp.append(0)
            all_scores.append(float(p_cls_scores[i]))

    return all_scores, all_tp, n_gt


def _interpolated_ap(
    all_scores: List[float],
    all_tp: List[int],
    n_gt: int,
) -> float:
    """11 点插值 AP（VOC 式 PR 曲线近似）；无 GT 或无预测时为 0。"""
    if n_gt == 0:
        return 0.0
    if not all_scores:
        return 0.0

    order = np.argsort(-np.asarray(all_scores))
    tp_arr = np.asarray(all_tp)[order]
    fp_arr = 1 - tp_arr
    tp_cum = np.cumsum(tp_arr)
    fp_cum = np.cumsum(fp_arr)
    recall = tp_cum / n_gt
    precision = tp_cum / (tp_cum + fp_cum + 1e-9)

    ap = 0.0
    for t in np.linspace(0, 1, 11):
        mask = recall >= t
        ap += float(precision[mask].max()) / 11 if mask.any() else 0.0
    return ap


def det_map(
    preds: Sequence[Dict],
    gts: Sequence[Dict],
    iou_threshold: float = 0.5,
    num_classes: Optional[int] = None,
) -> Dict[str, float]:
    """
    计算检测 mAP（VOC 式，单 IoU 阈值）。

    Args:
        preds: 每张图的预测，dict 含 ``boxes`` [N,4]、``scores`` [N]，
               ``labels`` [N]（numpy array 或 list）。
        gts: 每张图的标注，dict 含 ``boxes`` [M,4]、``labels`` [M]。
        iou_threshold: IoU 匹配阈值。
        num_classes: 类别数（None 时从 labels 推断）。

    Returns:
        dict: ``{"mAP": float, "class_0": float, ...}``
    """
    # 收集所有类别
    all_labels = set()
    for p in preds:
        all_labels.update(np.asarray(p.get("labels", [])).tolist())
    for g in gts:
        all_labels.update(np.asarray(g.get("labels", [])).tolist())
    if num_classes is not None:
        classes = list(range(num_classes))
    else:
        classes = sorted(all_labels) if all_labels else [0]

    aps: List[float] = []
    result: Dict[str, float] = {}

    for cls in classes:
        all_scores, all_tp, n_gt = _match_class_detections(
            preds, gts, cls, iou_threshold
        )
        ap = _interpolated_ap(all_scores, all_tp, n_gt)
        aps.append(ap)
        result[f"class_{cls}"] = ap

    result["mAP"] = float(np.mean(aps)) if aps else 0.0
    return result


# ============================== seg IoU ============================== #
def seg_iou(
    pred_mask: np.ndarray,
    gt_mask: np.ndarray,
) -> float:
    """
    计算分割 mask 的 IoU（二值或多类）。

    Args:
        pred_mask: 预测 mask [H,W]，int 或 bool。
        gt_mask: 标注 mask [H,W]，int 或 bool。

    Returns:
        float: 平均 IoU（多类时取各类均值，忽略背景 0）。
    """
    pred = np.asarray(pred_mask).astype(np.int32)
    gt = np.asarray(gt_mask).astype(np.int32)
    if pred.shape != gt.shape:
        raise ValueError(
            f"mask shape mismatch: {pred.shape} vs {gt.shape}"
        )

    labels = np.unique(np.concatenate([pred.ravel(), gt.ravel()]))
    labels = labels[labels != 0]  # 忽略背景
    if len(labels) == 0:
        return 0.0

    ious: List[float] = []
    for lbl in labels:
        p = pred == lbl
        g = gt == lbl
        inter = np.logical_and(p, g).sum()
        union = np.logical_or(p, g).sum()
        ious.append(inter / union if union > 0 else 0.0)
    return float(np.mean(ious))


# ============================== abdet AUROC ============================== #
def abdet_auroc(
    scores: Sequence[float],
    labels: Sequence[int],
) -> float:
    """
    计算异常检测 AUROC（ROC 曲线下面积）。

    Args:
        scores: 异常分数数组（越高越异常），[N]。
        labels: 真实标签数组（0=正常, 1=异常），[N]。

    Returns:
        float: AUROC ∈ [0, 1]。
    """
    s = np.asarray(scores, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int32)
    if len(s) < 2 or len(set(y.tolist())) < 2:
        return 0.0  # 样本不足或全是同一类

    # 按 score 降序排列
    order = np.argsort(-s)
    y_sorted = y[order]

    n_pos = float(np.sum(y == 1))
    n_neg = float(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        return 0.0

    # Wilcoxon-Mann-Whitney 统计量
    tp_cum = np.cumsum(y_sorted == 1)
    fp_cum = np.cumsum(y_sorted == 0)
    tpr = tp_cum / n_pos
    fpr = fp_cum / n_neg

    # 梯形法积分（numpy 2.0 移除了 trapz，用 trapezoid）
    trapz_fn = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    auc = trapz_fn(tpr, fpr)
    return float(auc)


# ============================== 便捷聚合 ============================== #
def evaluate_supervised(
    task: str,
    preds: Sequence,
    gts: Sequence,
    **kwargs,
) -> Dict[str, float]:
    """
    按任务类型自动分发到对应评估指标。

    Args:
        task: "det" / "seg" / "abdet"。
        preds: 预测列表。
        gts: 标注列表。
        **kwargs: 传递给具体指标函数的额外参数。

    Returns:
        dict: 指标名 → 值。
    """
    if task == "det":
        return det_map(preds, gts, **kwargs)
    elif task == "seg":
        ious = [seg_iou(p, g) for p, g in zip(preds, gts)]
        return {"mIoU": float(np.mean(ious)) if ious else 0.0}
    elif task == "abdet":
        # preds 为 scores list, gts 为 labels list
        return {"AUROC": abdet_auroc(preds, gts, **kwargs)}
    else:
        raise ValueError(f"不支持的任务类型: {task}")


__all__ = [
    "det_map",
    "seg_iou",
    "abdet_auroc",
    "evaluate_supervised",
]
