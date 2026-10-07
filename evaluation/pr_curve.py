"""PR 曲线与阈值调优选荐（W2-2，roadmap Wave2 评估增强）。

独立于 evaluation.eval_flow（该文件为并行批在途域，本模块自跑推理收集
原始检出）：LabelMe GT 框（矩形×2 + 多边形外接，全类别并为正类）vs
引擎低阈检出贪心 IoU 打 TP/FP → 阈值网格扫 P/R/F1 → F1 最优点即推荐
阈值。评估报告 JSON 落 workspace/eval_reports/。

纯后端模块（无 Qt）；engine 可注入（测试缝）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_IOU = 0.5
DEFAULT_CONF_FLOOR = 0.01
DEFAULT_GRID = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05~0.95


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _gt_boxes_from_labelme(doc: dict) -> list:
    """LabelMe shapes → GT 外接框（矩形×2；多边形/折线取点集外接）。"""
    boxes = []
    for sh in doc.get("shapes", []):
        pts = sh.get("points") or []
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def collect_detections(
    model_path: str,
    gt_dir: str,
    iou_t: float = DEFAULT_IOU,
    conf_floor: float = DEFAULT_CONF_FLOOR,
    max_images: int = 200,
    engine: Any = None,
    imread: Callable | None = None,
) -> dict:
    """收集原始检出并打 TP/FP 标（W2-2 FR-1）。

    Returns: {"detections": [(score, is_tp), ...], "n_gt": int,
              "n_images": int}——同分同图贪心独占匹配（一 GT 至多配一检）。
    """
    import json as _json

    eng = engine or _load_engine(model_path)
    read = imread or _default_imread
    detections: list[tuple[float, bool]] = []
    n_gt = 0
    n_images = 0
    names = sorted(
        f for f in os.listdir(gt_dir) if f.lower().endswith(".json")
    )[:max_images] if os.path.isdir(gt_dir) else []
    for name in names:
        try:
            with open(os.path.join(gt_dir, name), encoding="utf-8") as fh:
                doc = _json.load(fh)
        except (OSError, ValueError):
            continue
        gt = _gt_boxes_from_labelme(doc)
        n_gt += len(gt)
        img_path = _resolve_image(gt_dir, doc.get("imagePath") or "", name)
        if img_path is None:
            continue
        img = read(img_path)
        if img is None:
            continue
        n_images += 1
        res = eng.infer(img, threshold=conf_floor)
        boxes = getattr(res, "boxes", None)
        scores = tuple(getattr(res, "scores", ()) or ())
        if boxes is None or len(boxes) == 0:
            continue
        used = set()
        for i, box in enumerate(boxes):
            b = tuple(float(v) for v in box[:4])
            matched = False
            best_j, best_v = -1, iou_t
            for j, g in enumerate(gt):
                if j in used:
                    continue
                v = _iou(g, b)
                if v >= best_v:
                    best_v, best_j = v, j
            if best_j >= 0:
                used.add(best_j)
                matched = True
            detections.append((float(scores[i]) if i < len(scores) else 1.0,
                               matched))
    detections.sort(key=lambda d: -d[0])
    return {"detections": detections, "n_gt": n_gt, "n_images": n_images}


def pr_curve(
    collected: dict, grid: list[float] | None = None
) -> list[dict]:
    """阈值网格扫 P/R/F1（W2-2 FR-1）。

    P(t)=TP(t)/(TP(t)+FP(t))（无检出时 P=1 约定），R(t)=TP(t)/n_gt。
    """
    dets = collected.get("detections") or []
    n_gt = int(collected.get("n_gt") or 0)
    points = []
    for t in (grid or DEFAULT_GRID):
        tp = sum(1 for s, m in dets if s >= t and m)
        fp = sum(1 for s, m in dets if s >= t and not m)
        p = tp / (tp + fp) if (tp + fp) else 1.0
        r = tp / n_gt if n_gt else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        points.append({"threshold": t, "precision": p, "recall": r, "f1": f1})
    return points


def best_f1_point(points: list[dict]) -> dict:
    """F1 最优点（推荐阈值）；空输入返回显式不可用标记。"""
    if not points:
        return {"available": False, "reason": "无评估数据"}
    best = max(points, key=lambda p: p["f1"])
    return {"available": True, **best}


def save_eval_report(
    rows: list | None, pr: list[dict], best: dict, out_dir: str | None = None,
) -> str:
    """评估报告 JSON 落盘（W2-2 FR-1；workspace/eval_reports/）。"""
    from project.paths import resolve_base_root

    root = out_dir or os.path.join(resolve_base_root(), "eval_reports")
    os.makedirs(root, exist_ok=True)
    path = os.path.join(
        root, f"eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rows": rows or [],
            "pr_curve": pr,
            "best_f1": best,
        }, fh, ensure_ascii=False, indent=2)
    logger.info("评估报告已落盘: %s", path)
    return path


def _load_engine(model_path: str):
    from core.interfaces_supervised import TaskType
    from models.supervised.registry import get_engine

    eng = get_engine(TaskType.DET)
    eng.load(model_path, device="cpu")
    return eng


def _resolve_image(gt_dir: str, image_path: str, json_name: str):
    base = os.path.dirname(os.path.abspath(gt_dir))
    for cand in (
        os.path.join(gt_dir, image_path),
        os.path.join(base, image_path),
    ):
        if image_path and os.path.isfile(cand):
            return cand
    stem = os.path.splitext(json_name)[0]
    for ext in (".png", ".jpg", ".jpeg", ".bmp"):
        for d in (gt_dir, base):
            p = os.path.join(d, stem + ext)
            if os.path.isfile(p):
                return p
    return None


def _default_imread(path: str):
    from core.image_io import imread_unicode

    return imread_unicode(path)


__all__ = [
    "DEFAULT_GRID", "collect_detections", "pr_curve", "best_f1_point",
    "save_eval_report",
]
