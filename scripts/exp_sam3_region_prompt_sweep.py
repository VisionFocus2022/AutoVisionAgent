"""SAM3 矩形内分割松框悬崖优化扫描（W54）。

W53 实测悬崖：用户盒直发 m=0/8/16/64 = 0.755/0.486/0.275/0.136；固定紧提示
（点击±16+∩用户盒）m≥16 兜底 0.546 但离顶点远。本轮扫提示推导/选择策略：

  A2-f  比例缩放提示（主力假设）：prompt=点击居中、半边长=max(f×用户盒
        半边长, 16px 硬下限——W52 r=8 零实例教训)，nearest 选择，∩用户盒
        裁剪；f∈{0.5, 0.75}，全 margin
  A5    最小含点实例：prompt=用户盒直发（复用基线前向语义），选含点击点
        的最小实例（无含点实例时 fallback nearest），∩用户盒；全 margin
  A1    固定紧提示：prompt=点击±16，nearest，∩用户盒（补 m∈{0,8} 完整
        曲线——m≥16 已在 exp_sam3_region_rescue.py 测得 0.546）

证据门（PRD AC-2）：m=0 ≥0.74 且 m=16 ≥0.45 且 m=64 ≥0.30。
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
MARGINS = (0, 8, 16, 64)
PROMPT_FLOOR = 16.0  # 提示盒半边长下限（W52 r=8 零实例护栏）


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


def nearest_idx(masks, cx: float, cy: float) -> int:
    def _d(i):
        ys, xs = np.nonzero(masks[i])
        if len(xs) == 0:
            return 1e18
        return ((xs.mean() - cx) ** 2 + (ys.mean() - cy) ** 2) ** 0.5

    return min(range(len(masks)), key=_d)


def smallest_containing_idx(masks, cx: float, cy: float, h: int, w: int) -> int:
    """含点击点的最小实例（A5）；无含点实例 fallback nearest。"""
    yi, xi = min(int(cy), h - 1), min(int(cx), w - 1)
    cand = [i for i, m in enumerate(masks) if m[yi, xi]]
    if cand:
        return min(cand, key=lambda i: int(masks[i].sum()))
    return nearest_idx(masks, cx, cy)


def user_box_of(bx1, by1, bx2, by2, m, h, w):
    return [
        max(bx1 - m, 0), max(by1 - m, 0),
        min(bx2 + m, w - 1), min(by2 + m, h - 1),
    ]


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


def run_arm(arm: str, margins, make_prompt, select) -> None:
    for m in margins:
        t0 = time.time()
        ious = []
        for p, h, w, t, cx, cy, bx1, by1, bx2, by2 in targets:
            img = imread_unicode(p)
            ub = user_box_of(bx1, by1, bx2, by2, m, h, w)
            pb = make_prompt(cx, cy, ub, h, w)
            masks, _s = adapter._run_instances(img, boxes=[[pb]])
            if not masks:
                ious.append(0.0)
                continue
            best = masks[select(masks, cx, cy, h, w)]
            ious.append(poly_iou(_mask_to_polygon(clip_to_box(best, ub)), t, h, w))
        a = np.array(ious)
        print(
            f"[{arm:8} m={m:2}] mean={a.mean():.3f} median={np.median(a):.3f} "
            f">=0.5={(a >= 0.5).mean():.0%} 零产出={(a == 0).sum()} ({time.time()-t0:.0f}s)",
            flush=True,
        )


# ---- A2-f 比例缩放提示（主力假设，全 margin） ----
def _scaled_prompt_f(f: float):
    def _mk(cx, cy, ub, h, w):
        hw = max(f * (ub[2] - ub[0]) / 2, PROMPT_FLOOR)
        hh = max(f * (ub[3] - ub[1]) / 2, PROMPT_FLOOR)
        return [
            max(cx - hw, 0), max(cy - hh, 0),
            min(cx + hw, w - 1), min(cy + hh, h - 1),
        ]
    return _mk


run_arm("A2-50", MARGINS, _scaled_prompt_f(0.5), lambda ms, cx, cy, h, w: nearest_idx(ms, cx, cy))
run_arm("A2-75", MARGINS, _scaled_prompt_f(0.75), lambda ms, cx, cy, h, w: nearest_idx(ms, cx, cy))

# ---- A5 最小含点实例（用户盒直发前向，仅选择不同，全 margin） ----
run_arm(
    "A5", MARGINS,
    lambda cx, cy, ub, h, w: [float(v) for v in ub],
    lambda ms, cx, cy, h, w: smallest_containing_idx(ms, cx, cy, h, w),
)

# ---- A1 固定紧提示（补 m∈{0,8} 完整曲线；m≥16 已测 0.546） ----
def _tight_prompt(cx, cy, ub, h, w):
    return [
        max(cx - 16, 0), max(cy - 16, 0),
        min(cx + 16, w - 1), min(cy + 16, h - 1),
    ]


run_arm("A1", (0, 8), _tight_prompt, lambda ms, cx, cy, h, w: nearest_idx(ms, cx, cy))
