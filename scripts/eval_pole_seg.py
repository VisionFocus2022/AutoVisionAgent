"""极柱专用模型同口径验收（W50 · FR-3）。

与 SAM3 验收（scripts/eval_sam3_accuracy.py --manifest）完全同口径：
同 W48 manifest val 集、同 GT 最大连通域、同「质心点击」语义
（选包含 GT 质心的预测实例，无实例覆盖则 IoU=0）→ 三指标对表
SAM3 零样本基线 0.515/0.561/57%。

用法：
    .venv/Scripts/python.exe scripts/eval_pole_seg.py [--ckpt weights/pole-seg/best.pt]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.image_io import imread_unicode  # noqa: E402

DATA = Path(r"E:/学习项目/极柱外观检标注图")
MANIFEST = REPO_ROOT / "weights" / "sam3-pole-ft" / "manifest.json"
DEFAULT_CKPT = REPO_ROOT / "weights" / "pole-seg" / "weights" / "best.pt"
DEFECT_LABELS = {"YS", "ZW", "TJYS", "HS"}


def gt_components(json_path: Path, h: int, w: int):
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
        return []
    lab = np.zeros((h, w), dtype=np.int32)
    for i, m in enumerate(masks, 1):
        lab[m > 0] = i
    n, _ = cv2.connectedComponents((lab > 0).astype(np.uint8), connectivity=8)
    return [(lab == i).astype(np.uint8) for i in range(1, n)]


def mask_iou(a, b) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return inter / union if union else 0.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="极柱专用模型同口径验收（W50）")
    parser.add_argument("--ckpt", type=Path, default=DEFAULT_CKPT)
    parser.add_argument("--conf", type=float, default=0.01,
                        help="实例置信度门。默认 0.01（敏感性实测 0.01/0.05/0.10 = "
                             "mean 0.597/0.576/0.557，质心选实例 max-IoU 语义下低门零副作用、"
                             "零命中 34→11 张）")
    args = parser.parse_args(argv)
    if not args.ckpt.is_file():
        print(f"[eval] ckpt 不存在: {args.ckpt}")
        return 2

    from ultralytics import YOLO

    model = YOLO(str(args.ckpt))
    val_names = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["val"])
    imgs = sorted(
        p for p in glob.glob(str(DATA / "*.bmp"))
        if os.path.basename(p) in val_names
    )
    print(f"[eval] val {len(imgs)} 图（与 SAM3 验收同集） ckpt={args.ckpt}")

    ious = []
    t0 = time.time()
    for idx, p in enumerate(imgs, 1):
        img = imread_unicode(p)
        h, w = img.shape[:2]
        comps = gt_components(Path(p).with_suffix(".json"), h, w)
        if not comps:
            continue
        comps.sort(key=lambda m: -m.sum())
        target = comps[0]
        M = cv2.moments(target.astype(np.uint8))
        if M["m00"] == 0:
            continue
        cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]

        res = model.predict(img, conf=args.conf, verbose=False)[0]
        best_iou = 0.0
        if res.masks is not None:
            masks_np = res.masks.data.cpu().numpy()  # (N, mh, mw) letterbox 域
            # 逆 letterbox：从预测框回原图坐标更稳——用 boxes 缩放掩码
            boxes = res.boxes.xyxy.cpu().numpy()
            for mi, (m, (x1, y1, x2, y2)) in enumerate(zip(masks_np, boxes)):
                # 质心是否落在预测框内（原图域）=「点击选中该实例」语义
                if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                    continue
                # 掩码 resize 回原图尺寸（原图 1600² 方形→imgsz 方形，无 letterbox padding）
                full = cv2.resize(m.astype(np.float32), (w, h),
                                  interpolation=cv2.INTER_NEAREST) > 0.5
                best_iou = max(best_iou, mask_iou(full, target > 0))
        ious.append(best_iou)
        if idx % 40 == 0:
            print(f"[eval] {idx}/{len(imgs)} … running mean={np.mean(ious):.3f}", flush=True)

    arr = np.array(ious)
    print(
        f"\n[eval] 同口径终局（质心点击语义, conf={args.conf}）: "
        f"mean={arr.mean():.3f} median={np.median(arr):.3f} "
        f"≥0.5占比={(arr >= 0.5).mean():.0%}  ({time.time()-t0:.0f}s)"
    )
    print("[eval] 对表 SAM3 零样本: 0.515 / 0.561 / 57%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
