"""SAM3 标注精度基线（W47 · 取证）：极柱 GT 量化各模式误差。

模式A 点击：GT 最大连通域质心 → predict_point → 与该连通域 IoU
模式B 概念：build_amg_detector("hole") → 逐实例对 GT 的命中/精确率/召回
输出：每模式 mean/median IoU + 失败率——定位「不准确」的主导来源。
"""
import glob
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(r"E:/学习项目/视觉大模型")
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from labeling.sam3_adapter import Sam3Adapter  # noqa: E402
from core.image_io import imread_unicode  # noqa: E402

DATA = Path(r"E:/学习项目/极柱外观检标注图")
DEFECT_LABELS = {"YS", "ZW", "TJYS", "HS"}
N_IMG = 12


def gt_masks(json_path, h, w):
    import json

    doc = json.loads(json_path.read_text(encoding="utf-8"))
    comps = []
    for s in doc.get("shapes", []):
        if s.get("label") not in DEFECT_LABELS or s.get("shape_type") != "polygon":
            continue
        pts = np.asarray(s.get("points", []), dtype=np.int32)
        if len(pts) < 3:
            continue
        m = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(m, [pts], 1)
        comps.append(m)
    if not comps:
        return []
    lab = np.zeros((h, w), dtype=np.int32)
    for i, m in enumerate(comps, 1):
        lab[m > 0] = i
    n, _ = cv2.connectedComponents((lab > 0).astype(np.uint8), connectivity=8)
    out = []
    for cid in range(1, n):
        out.append((lab == cid).astype(np.uint8))
    return out


def mask_iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return inter / union if union else 0.0


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="SAM3 极柱标注精度评估（W47/W48）")
    ap.add_argument("--ckpt", default=str(REPO / "weights/sam3"),
                    help="模型目录（微调产物 weights/sam3-pole-ft 可指）")
    ap.add_argument("--manifest", default=None,
                    help="finetune manifest.json——限定 val 留出集（防训练集泄漏）")
    ap.add_argument("--n", type=int, default=N_IMG)
    _args = ap.parse_args()
    if _args.manifest:
        _val = set(json.loads(Path(_args.manifest).read_text(encoding="utf-8"))["val"])
        imgs = sorted(
            p for p in glob.glob(str(DATA / "*.bmp"))
            if os.path.basename(p) in _val
        )[: _args.n]
    else:
        imgs = sorted(
            p for p in glob.glob(str(DATA / "*.bmp"))
            if not os.path.basename(p).startswith("(")
        )[: _args.n]
else:  # 被 import 时不执行采集（eval 函数另行使用）
    import json  # noqa: F401 — manifest 分支复用
    _args = type("_A", (), {"ckpt": str(REPO / "weights/sam3")})()
    imgs = []
print(f"[eval] {len(imgs)} 缺陷图 ckpt={_args.ckpt}")

t0 = time.time()
adapter = Sam3Adapter()
adapter.load(_args.ckpt, device="cuda")
print(f"[eval] 模型加载 {time.time()-t0:.1f}s", flush=True)

ious_click, click_fail = [], 0
rows = []
for p in imgs:
    img = imread_unicode(p)
    h, w = img.shape[:2]
    comps = gt_masks(Path(p).with_suffix(".json"), h, w)
    if not comps:
        continue
    comps.sort(key=lambda m: -m.sum())
    target = comps[0]
    M = cv2.moments(target.astype(np.uint8))
    if M["m00"] == 0:
        continue
    cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]

    t1 = time.time()
    poly = adapter.predict_point(img, (cx, cy))
    dt = time.time() - t1
    if len(poly) < 3:
        click_fail += 1
        rows.append((os.path.basename(p), int(target.sum()), 0.0, dt, "EMPTY"))
        continue
    pred = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(pred, [np.asarray(poly, dtype=np.int32)], 1)
    iou = mask_iou(pred > 0, target > 0)
    ious_click.append(iou)
    rows.append((os.path.basename(p), int(target.sum()), iou, dt, ""))

print("\n== 模式A 点击（质心 → predict_point）==")
for r in rows:
    tag = r[4] or f"IoU={r[2]:.3f}"
    print(f"  {r[0][:24]:26} GT面积={r[1]:6}px  {tag}  {r[3]:.1f}s")
if ious_click:
    print(f"  有效: mean={np.mean(ious_click):.3f} median={np.median(ious_click):.3f} "
          f"≥0.5占比={np.mean(np.array(ious_click) >= 0.5):.0%}  空产出={click_fail}")

print("\n== 模式B 概念（hole 全图）==", flush=True)
prec_all, rec_all, best_ious = [], [], []
for p in imgs:
    img = imread_unicode(p)
    h, w = img.shape[:2]
    comps = gt_masks(Path(p).with_suffix(".json"), h, w)
    if not comps:
        continue
    gt_union = np.zeros((h, w), dtype=bool)
    for m in comps:
        gt_union |= m > 0
    masks, scores = adapter._run_instances(img, text="hole")
    big = [m for m in masks if m.sum() >= 64]
    if not big:
        prec_all.append(0.0); rec_all.append(0.0); best_ious.append(0.0)
        print(f"  {os.path.basename(p)[:24]:26} 零实例")
        continue
    hits = sum(1 for m in big if mask_iou(m > 0, gt_union) >= 0.1)
    prec_all.append(hits / len(big))
    pred_union = np.zeros_like(gt_union)
    for m in big:
        pred_union |= m > 0
    rec_all.append((np.logical_and(pred_union, gt_union).sum() / gt_union.sum()) if gt_union.sum() else 0)
    best_ious.append(max(mask_iou(m > 0, gt_union) for m in big))
    print(f"  {os.path.basename(p)[:24]:26} 实例={len(big)} 命中={hits} 精确率={hits/len(big):.0%} "
          f"GT覆盖={rec_all[-1]:.0%} 最佳IoU={best_ious[-1]:.3f}")
print(f"  汇总: 精确率 mean={np.mean(prec_all):.0%}  GT覆盖 mean={np.mean(rec_all):.0%}  "
      f"最佳IoU mean={np.mean(best_ious):.3f}")
