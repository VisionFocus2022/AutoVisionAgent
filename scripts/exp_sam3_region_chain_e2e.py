"""SAM3 矩形内分割自适应链端到端验证（W54 · 生产真实路径）。

链已上产 predict_point_in_box（直发用户盒 → fill≥0.85 收紧 f=0.5 点击
居中盒 → 再收紧 点击±16）。本脚本经**生产方法真实路径**复测（W53 教训：
不复刻逻辑），val 162 × margin {0,8,16,64}，同时统计前向次数（成本）。

证据门（PRD AC-2）：m=0 ≥0.74 且 m=16 ≥0.45 且 m=64 ≥0.30。
基线锚：直发 0.755/0.486/0.275/0.136；固定紧提示兜底 0.546。
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
MARGINS = (0, 8, 16, 64)


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


val = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["val"])
imgs = sorted(
    p for p in glob.glob(str(DATA / "*.bmp")) if os.path.basename(p) in val
)
print(f"[e2e] val {len(imgs)} 图", flush=True)

adapter = Sam3Adapter()
adapter.load(str(REPO_ROOT / "weights/sam3"), device="cuda")

# 前向计数 wrapper（成本证据：链的额外前向只在侵占时发生）
_raw_run = adapter._run_instances
_fwd_counter = {"n": 0}


def _counting_run(image, text=None, boxes=None):
    _fwd_counter["n"] += 1
    return _raw_run(image, text=text, boxes=boxes)


adapter._run_instances = _counting_run

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
print(f"[e2e] 有效目标 {len(targets)}", flush=True)

for margin in MARGINS:
    t0 = time.time()
    _fwd_counter["n"] = 0
    ious = []
    for p, h, w, t, cx, cy, bx1, by1, bx2, by2 in targets:
        img = imread_unicode(p)
        ub = (
            max(bx1 - margin, 0), max(by1 - margin, 0),
            min(bx2 + margin, w - 1), min(by2 + margin, h - 1),
        )
        poly = adapter.predict_point_in_box(img, (cx, cy), ub)
        ious.append(poly_iou(poly, t, h, w))
    a = np.array(ious)
    print(
        f"[链 m={margin:2}] mean={a.mean():.3f} median={np.median(a):.3f} "
        f">=0.5={(a >= 0.5).mean():.0%} 零产出={(a == 0).sum()} "
        f"前向均={_fwd_counter['n'] / len(targets):.2f}次 ({time.time()-t0:.0f}s)",
        flush=True,
    )
