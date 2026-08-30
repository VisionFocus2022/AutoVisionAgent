"""SAM3 区域分割松框检测器诊断（W54 · 路由器证据采集）。

端到端链实测证伪单阈值 fill 检测（m=16 仅 0.319/前向 1.10——大结构掩码
对盒填充率典型 0.6-0.7，阈值 0.85 几乎不触发；下调又误伤紧框正确抓取）。
本脚本逐图记录候选检测器特征 + 直发/±16 双臂结果，供离线路由器搜索：

每 (图, margin) 记录（直发前向一次 + ±16 前向一次）：
  - 直发：fill(掩码∩盒/盒)、spill(掩码∩盒外/掩码)、bbox 包含度
    （掩码 bbox 与用户盒交集/掩码 bbox 面积）、IoU
  - ±16 紧提示：fill/spill/IoU（对用户盒裁剪后）
落盘 JSON：weights/sam3-pole-ft/router_diag_w54.json
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
OUT = REPO_ROOT / "weights/sam3-pole-ft/router_diag_w54.json"


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
    inter = np.logical_and(
        (cv2.fillPoly(np.zeros((h, w), np.uint8), [np.asarray(poly, np.int32)], 1) > 0),
        target > 0,
    ).sum()
    union = np.logical_or(
        (cv2.fillPoly(np.zeros((h, w), np.uint8), [np.asarray(poly, np.int32)], 1) > 0),
        target > 0,
    ).sum()
    return inter / union if union else 0.0


def clip_mask(mask: np.ndarray, box) -> np.ndarray:
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


def features(mask: np.ndarray, ub, h: int, w: int) -> dict:
    """候选检测器特征（掩码 vs 用户盒几何关系）。"""
    m = mask.astype(bool)
    box_area = max((ub[3] - ub[1] + 1) * (ub[2] - ub[0] + 1), 1)
    m_area = int(m.sum())
    if m_area == 0:
        return {"fill": 0.0, "spill": 0.0, "bbox_in": 0.0, "area": 0}
    inter_box = int(clip_mask(m.astype(np.uint8), ub).sum())
    fill = inter_box / box_area
    spill = (m_area - inter_box) / m_area
    ys, xs = np.nonzero(m)
    mb = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    mb_area = (mb[3] - mb[1] + 1) * (mb[2] - mb[0] + 1)
    ix1, iy1 = max(mb[0], ub[0]), max(mb[1], ub[1])
    ix2, iy2 = min(mb[2], ub[2]), min(mb[3], ub[3])
    inter_bbox = max(ix2 - ix1 + 1, 0) * max(iy2 - iy1 + 1, 0)
    return {
        "fill": round(fill, 4),
        "spill": round(spill, 4),
        "bbox_in": round(inter_bbox / mb_area, 4),
        "area": m_area,
    }


val = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["val"])
imgs = sorted(
    p for p in glob.glob(str(DATA / "*.bmp")) if os.path.basename(p) in val
)
print(f"[diag] val {len(imgs)} 图", flush=True)

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
        # 直发臂
        masks, _s = adapter._run_instances(img, boxes=[[ub]])
        if not masks:
            records.append({"img": os.path.basename(p), "m": margin, "direct": None})
            continue
        dm = nearest_mask(masks, cx, cy)
        rec = {
            "img": os.path.basename(p), "m": margin,
            "direct": {**features(dm, ub, h, w),
                       "iou": round(poly_iou(_mask_to_polygon(clip_mask(dm, ub)), t, h, w), 4)},
        }
        # ±16 紧提示臂（对用户盒裁剪）
        tb = [
            max(cx - 16, 0), max(cy - 16, 0),
            min(cx + 16, w - 1), min(cy + 16, h - 1),
        ]
        masks2, _s2 = adapter._run_instances(img, boxes=[[tb]])
        if masks2:
            tm = nearest_mask(masks2, cx, cy)
            rec["tight"] = {**features(tm, ub, h, w),
                            "iou": round(poly_iou(_mask_to_polygon(clip_mask(tm, ub)), t, h, w), 4)}
        else:
            rec["tight"] = None
        records.append(rec)
    if len(records) % 160 == 0:
        print(f"[diag] {len(records)} 条 ({time.time()-t_start:.0f}s)", flush=True)

OUT.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
print(f"[diag] 完成 {len(records)} 条 → {OUT} ({time.time()-t_start:.0f}s)", flush=True)
