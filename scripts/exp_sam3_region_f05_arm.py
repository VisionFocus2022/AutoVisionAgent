"""SAM3 区域分割 f=0.5 臂特征补录（W54 路由 v4 证据）。

双臂诊断（router_diag_w54.json）证明 direct/tight 两臂特征在 m=0 误路由
尾部重叠（tight 残片 IoU 0.19 vs m=16 好抓 tight IoU 0.60，fill 无法分）。
路由 v4 引入 f=0.5 缩放臂作二级参照：
  疑松判据 = area(f05)/area(direct) ≤ 0.4（同物比值≈1，抓大则≪1）
  f05 自身抓大判据 = fill(f05_mask, f05_prompt) ≥ θf2
本脚本逐图记录 f05 臂特征（全量 648 条），落盘供离线路由搜索。
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

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from core.image_io import imread_unicode  # noqa: E402
from labeling.sam3_adapter import Sam3Adapter, _mask_to_polygon  # noqa: E402

DATA = Path(r"E:/学习项目/极柱外观检标注图")
MANIFEST = REPO_ROOT / "weights/sam3-pole-ft/manifest.json"
DEFECT_LABELS = {"YS", "ZW", "TJYS", "HS"}
MARGINS = (0, 8, 16, 64)
OUT = REPO_ROOT / "weights/sam3-pole-ft/router_diag_w54_f05.json"


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


def poly_iou(poly, target, h: int, w: int) -> float:
    if len(poly) < 3:
        return 0.0
    pred = np.zeros((h, w), np.uint8)
    cv2.fillPoly(pred, [np.asarray(poly, np.int32)], 1)
    inter = np.logical_and(pred > 0, target > 0).sum()
    union = np.logical_or(pred > 0, target > 0).sum()
    return inter / union if union else 0.0


def clip_mask(mask: np.ndarray, box) -> np.ndarray:
    m8 = mask.astype(np.uint8)
    c = np.zeros_like(m8)
    y_lo, y_hi = max(int(box[1]), 0), min(int(box[3]) + 1, m8.shape[0])
    x_lo, x_hi = max(int(box[0]), 0), min(int(box[2]) + 1, m8.shape[1])
    c[y_lo:y_hi, x_lo:x_hi] = m8[y_lo:y_hi, x_lo:x_hi]
    return c


def fill_of(mask: np.ndarray, box) -> float:
    m8 = mask.astype(np.uint8)
    y_lo, y_hi = max(int(box[1]), 0), min(int(box[3]) + 1, m8.shape[0])
    x_lo, x_hi = max(int(box[0]), 0), min(int(box[2]) + 1, m8.shape[1])
    area = (y_hi - y_lo) * (x_hi - x_lo)
    if area <= 0:
        return 0.0
    return int(clip_mask(m8, box).sum()) / area


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
print(f"[f05] val {len(imgs)} 图", flush=True)

adapter = Sam3Adapter()
adapter.load(str(REPO_ROOT / "weights/sam3"), device="cuda")

records = []
t_start = time.time()
for p in imgs:
    img = imread_unicode(p)
    h, w = img.shape[:2]
    t = gt_target(Path(p).with_suffix(".json"), h, w)
    if t is None:
        continue
    M = cv2.moments(t.astype(np.uint8))
    if M["m00"] == 0:
        continue
    cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
    ys, xs = np.nonzero(t)
    for margin in MARGINS:
        ub = [
            max(int(xs.min()) - margin, 0), max(int(ys.min()) - margin, 0),
            min(int(xs.max()) + margin, w - 1), min(int(ys.max()) + margin, h - 1),
        ]
        hw = max(0.5 * (ub[2] - ub[0]) / 2, 16.0)
        hh = max(0.5 * (ub[3] - ub[1]) / 2, 16.0)
        fb = [
            max(cx - hw, 0), max(cy - hh, 0),
            min(cx + hw, w - 1), min(cy + hh, h - 1),
        ]
        masks, _s = adapter._run_instances(img, boxes=[[fb]])
        if not masks:
            records.append({"img": os.path.basename(p), "m": margin, "f05": None})
            continue
        fm = nearest_mask(masks, cx, cy)
        records.append({
            "img": os.path.basename(p), "m": margin,
            "f05": {
                "area": int(fm.sum()),
                "fill_prompt": round(fill_of(fm, fb), 4),
                "fill_user": round(fill_of(fm, ub), 4),
                "iou": round(poly_iou(_mask_to_polygon(clip_mask(fm, ub)), t, h, w), 4),
            },
        })
    if len(records) % 160 == 0:
        print(f"[f05] {len(records)} 条 ({time.time()-t_start:.0f}s)", flush=True)

OUT.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
print(f"[f05] 完成 {len(records)} 条 → {OUT} ({time.time()-t_start:.0f}s)", flush=True)
