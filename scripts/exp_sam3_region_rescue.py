"""SAM3 矩形内分割松框救援实验（W53 补充）：悬崖定位 + 混合策略臂。

主实验（exp_sam3_region_caliber.py）结论：紧框 m=0 nearest 0.755/99%/0，
松框悬崖 m=16 0.275、m=64 0.136——盒提示语义随盒大小质变（W52 半径
悬崖同族现象：大盒引导到大结构，掩码∩盒裁片与 GT 不重叠）。
本补充两问：
  A. 悬崖边在哪：m=8 用户盒直发（argmax/nearest）
  B. 松框可否救回：m∈{16,64} 混合策略——提示盒=点击±16px（与
     predict_point v2 同参）+ nearest 选择 + 掩码∩用户矩形硬约束
     （W43 裁剪语义保留）。对照锚：点击口径 0.546/572/63%。
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(r"E:/学习项目/视觉大模型")
sys.path.insert(0, str(REPO_ROOT))

import cv2  # noqa: E402  # sys.path 注入后方可导入仓库依赖
import numpy as np  # noqa: E402  # 同上

from core.image_io import imread_unicode  # noqa: E402  # 同上
from labeling.sam3_adapter import (  # noqa: E402  # 同上, _mask_to_polygon
    Sam3Adapter,
    _mask_to_polygon,
)

DATA = Path(r"E:/学习项目/极柱外观检标注图")
MANIFEST = REPO_ROOT / "weights/sam3-pole-ft/manifest.json"
DEFECT_LABELS = {"YS", "ZW", "TJYS", "HS"}
HYB_R = 16  # 混合策略紧提示盒半边长（predict_point v2 同参）


def gt_target(json_path: Path, h: int, w: int):
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    masks = []
    for s in doc.get("shapes", []):
        if s.get("label") not in DEFECT_LABELS or s.get("shape_type") != "polygon":
            continue
        pts = np.asarray(s.get("points", []), dtype=np.int32)
        if len(pts) < 3:
            continue
        m = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(m, [pts], 1)
        masks.append(m)
    if not masks:
        return None
    lab = np.zeros((h, w), dtype=np.int32)
    for i, m in enumerate(masks, 1):
        lab[m > 0] = i
    n, _ = cv2.connectedComponents((lab > 0).astype(np.uint8), connectivity=8)
    comps = [(lab == i).astype(np.uint8) for i in range(1, n)]
    comps.sort(key=lambda m: -int(m.sum()))
    return comps[0]


def mask_iou(a, b) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return inter / union if union else 0.0


def poly_iou(poly, target, h: int, w: int) -> float:
    if len(poly) < 3:
        return 0.0
    pred = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(pred, [np.asarray(poly, dtype=np.int32)], 1)
    return mask_iou(pred > 0, target > 0)


def clip_to_box(mask: np.ndarray, box) -> np.ndarray:
    m8 = mask.astype(np.uint8)
    c = np.zeros_like(m8)
    y_lo, y_hi = max(int(box[1]), 0), min(int(box[3]) + 1, m8.shape[0])
    x_lo, x_hi = max(int(box[0]), 0), min(int(box[2]) + 1, m8.shape[1])
    c[y_lo:y_hi, x_lo:x_hi] = m8[y_lo:y_hi, x_lo:x_hi]
    return c


def nearest_mask(masks, cx: float, cy: float):
    def _d(m):
        ys, xs = np.nonzero(m)
        if len(xs) == 0:
            return 1e18
        return ((xs.mean() - cx) ** 2 + (ys.mean() - cy) ** 2) ** 0.5

    return min(masks, key=_d)


val = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["val"])
imgs = sorted(
    p for p in glob.glob(str(DATA / "*.bmp")) if os.path.basename(p) in val
)
print(f"[exp] val {len(imgs)} 图", flush=True)

adapter = Sam3Adapter()
adapter.load(str(REPO_ROOT / "weights/sam3"), device="cuda")

targets = []
for p in imgs:
    img = imread_unicode(p)
    h, w = img.shape[:2]
    t = gt_target(Path(p).with_suffix(".json"), h, w)
    if t is None:
        continue
    M = cv2.moments(t.astype(np.uint8))
    if M["m00"] == 0:
        continue
    ys, xs = np.nonzero(t)
    targets.append((
        p, h, w, t,
        M["m10"] / M["m00"], M["m01"] / M["m00"],
        int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()),
    ))
print(f"[exp] 有效目标 {len(targets)}", flush=True)

# ---- A: m=8 悬崖边（用户盒直发，双选择） ----
t0 = time.time()
res = {"argmax": [], "nearest": []}
for p, h, w, t, cx, cy, bx1, by1, bx2, by2 in targets:
    img = imread_unicode(p)
    box = [
        max(bx1 - 8, 0), max(by1 - 8, 0),
        min(bx2 + 8, w - 1), min(by2 + 8, h - 1),
    ]
    masks, scores = adapter._run_instances(img, boxes=[[box]])
    if not masks:
        for v in res.values():
            v.append(0.0)
        continue
    best_a = masks[int(np.argmax(scores))] if scores else masks[0]
    res["argmax"].append(
        poly_iou(_mask_to_polygon(clip_to_box(best_a, box)), t, h, w)
    )
    res["nearest"].append(
        poly_iou(
            _mask_to_polygon(clip_to_box(nearest_mask(masks, cx, cy), box)),
            t, h, w,
        )
    )
for k, v in res.items():
    a = np.array(v)
    print(
        f"[A m= 8 选择={k:8}] mean={a.mean():.3f} median={np.median(a):.3f} "
        f">=0.5={(a >= 0.5).mean():.0%} 零产出={(a == 0).sum()} ({time.time()-t0:.0f}s)",
        flush=True,
    )

# ---- B: 松框救援混合策略（提示盒=点击±16，nearest，∩用户矩形） ----
for margin in (16, 64):
    t0 = time.time()
    ious = []
    for p, h, w, t, cx, cy, bx1, by1, bx2, by2 in targets:
        img = imread_unicode(p)
        user_box = [
            max(bx1 - margin, 0), max(by1 - margin, 0),
            min(bx2 + margin, w - 1), min(by2 + margin, h - 1),
        ]
        prompt = [
            max(cx - HYB_R, 0), max(cy - HYB_R, 0),
            min(cx + HYB_R, w - 1), min(cy + HYB_R, h - 1),
        ]
        masks, _scores = adapter._run_instances(img, boxes=[[prompt]])
        if not masks:
            ious.append(0.0)
            continue
        best = nearest_mask(masks, cx, cy)
        ious.append(
            poly_iou(_mask_to_polygon(clip_to_box(best, user_box)), t, h, w)
        )
    a = np.array(ious)
    print(
        f"[B m={margin:2} 混合=紧提示+∩用户盒] mean={a.mean():.3f} "
        f"median={np.median(a):.3f} >=0.5={(a >= 0.5).mean():.0%} "
        f"零产出={(a == 0).sum()} ({time.time()-t0:.0f}s)",
        flush=True,
    )
