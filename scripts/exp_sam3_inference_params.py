"""SAM3 推理参数敏感性实验（W52）：val 162 图全量基线 + 提示盒半径扫描 + 实例选择策略对比。

W47 证伪裁剪窗/概念词；W48 证伪解码器微调；本轮测推理端最后两组杠杆：
A. _CLICK_BOX_R 半径（8/16/32/64）——盒提示语义=引导非裁剪，半径可能影响实例粒度
B. 实例选择策略（argmax 分数 vs 含点击点 vs 最近距离）——W47 仅 12 图粗测
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
from labeling.sam3_adapter import Sam3Adapter  # noqa: E402  # 同上

DATA = Path(r"E:/学习项目/极柱外观检标注图")
MANIFEST = REPO_ROOT / "weights/sam3-pole-ft/manifest.json"
DEFECT_LABELS = {"YS", "ZW", "TJYS", "HS"}


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


def poly_iou(poly, target, h, w):
    if len(poly) < 3:
        return 0.0
    pred = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(pred, [np.asarray(poly, dtype=np.int32)], 1)
    return mask_iou(pred > 0, target > 0)


val = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["val"])
imgs = sorted(
    p for p in glob.glob(str(DATA / "*.bmp")) if os.path.basename(p) in val
)
print(f"[exp] val {len(imgs)} 图", flush=True)

adapter = Sam3Adapter()
adapter.load(str(REPO_ROOT / "weights/sam3"), device="cuda")

# 预取 GT（质心 + 目标掩码）一次
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
    targets.append((p, h, w, t, M["m10"] / M["m00"], M["m01"] / M["m00"]))
print(f"[exp] 有效目标 {len(targets)}", flush=True)

# ---- A: 半径扫描（实例选择=现 argmax）----
import labeling.sam3_adapter as sa  # noqa: E402  # A 节就地导入（前有可执行代码）

for radius in (8, 16, 32, 64):
    sa._CLICK_BOX_R = radius
    t0 = time.time()
    ious = []
    for p, h, w, t, cx, cy in targets:
        img = imread_unicode(p)
        poly = adapter.predict_point(img, (cx, cy))
        ious.append(poly_iou(poly, t, h, w))
    a = np.array(ious)
    print(
        f"[A 半径={radius:3}] mean={a.mean():.3f} median={np.median(a):.3f} "
        f">=0.5={(a >= 0.5).mean():.0%} 零产出={(a == 0).sum()} ({time.time()-t0:.0f}s)",
        flush=True,
    )
sa._CLICK_BOX_R = 16

# ---- B: 实例选择策略（半径=16 现值，_run_instances 原始实例池重选）----
t0 = time.time()
sel = {"argmax": [], "contains": [], "nearest": []}
for p, h, w, t, cx, cy in targets:
    img = imread_unicode(p)
    r = 16.0
    box = [max(cx - r, 0), max(cy - r, 0), min(cx + r, w - 1), min(cy + r, h - 1)]
    masks, scores = adapter._run_instances(img, boxes=[[box]])
    if not masks:
        for v in sel.values():
            v.append(0.0)
        continue
    # argmax 分数
    best = masks[int(np.argmax(scores))]
    poly = sa._mask_to_polygon(best)
    sel["argmax"].append(poly_iou(poly, t, h, w))
    # 含点击点
    yi, xi = min(int(cy), h - 1), min(int(cx), w - 1)
    cand = [i for i, m in enumerate(masks) if m[yi, xi]]
    pool = cand if cand else list(range(len(masks)))
    best_c = max(pool, key=lambda i: int(masks[i].sum()))
    sel["contains"].append(poly_iou(sa._mask_to_polygon(masks[best_c]), t, h, w))
    # 距点击最近（掩码质心距离）
    def _centroid_dist(m, cx=cx, cy=cy):
        ys, xs = np.nonzero(m)
        if len(xs) == 0:
            return 1e9
        return ((xs.mean() - cx) ** 2 + (ys.mean() - cy) ** 2) ** 0.5

    best_n = min(pool, key=lambda i: _centroid_dist(masks[i]))
    sel["nearest"].append(poly_iou(sa._mask_to_polygon(masks[best_n]), t, h, w))

for k, v in sel.items():
    a = np.array(v)
    print(
        f"[B 选择={k:9}] mean={a.mean():.3f} median={np.median(a):.3f} "
        f">=0.5={(a >= 0.5).mean():.0%} 零产出={(a == 0).sum()} ({time.time()-t0:.0f}s/三策略)",
        flush=True,
    )
