"""SAM3 极柱域微调（W48 · docs/prd-sam3-pole-finetune.md）。

冻结 vision(454M)/text(353M) 塔，微调解码器栈（geometry+detr_enc+
detr_dec+mask_dec+dot_product ≈32.6M，探针实测 12GB 显存宽裕）：
单实例盒提示样本式训练（GT 多边形 + bbox±10% 抖动 + 翻转增强），
DETR 匈牙利匹配 → 正查询 focal+dice 掩码损失（v1.1：objectness 弃用）。
验收标尺 = scripts/eval_sam3_accuracy.py（val 留出集点击模式 mean IoU，
基线 0.559，目标 ≥0.70）。

用法：
    # 冒烟（3 样本 2 步 + 2 图 val + ckpt 存取 + adapter 复载验证）
    .venv/Scripts/python.exe scripts/finetune_sam3.py --smoke

    # 全量（后台约 2h；最优 ckpt 按 val 点击 IoU 落 weights/sam3-pole-ft）
    .venv/Scripts/python.exe scripts/finetune_sam3.py

产物目录（weights/ 已 gitignore）：sam3-pole-ft/{config,model.safetensors,
processor/*, manifest.json, history.json}——AVA_SAM3_DIR 指向即接入。
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = Path(r"E:/学习项目/极柱外观检标注图")
DEFAULT_BASE = REPO_ROOT / "weights" / "sam3"
DEFAULT_OUT = REPO_ROOT / "weights" / "sam3-pole-ft"

DEFECT_LABELS = {"YS", "ZW", "TJYS", "HS"}
# v1.1：dot_product_scoring 移出可训集并弃用 objectness 损失——v1.0 全量
# objectness focal（1 正/199 负）一 epoch 把分布整体压塌（max 2.69→-1.65，
# 推理阈值 0.3 全滤空，val IoU 0.000）；冻结评分头保住预训练分数校准，
# 推理端按分数选实例与监督端按代价选查询天然对齐。
TRAINABLE_MODULES = (
    "geometry_encoder", "detr_encoder", "detr_decoder", "mask_decoder",
)
FOCAL_ALPHA = 0.25
FOCAL_GAMMA = 2.0
FOCAL_WEIGHT = 20.0  # SAM 家族掩码损失惯例 focal:dice ≈ 20:1


# ================================ 纯函数（单测面） ================================ #


def extract_defect_shapes(json_path: Path) -> List[np.ndarray]:
    """LabelMe JSON → 缺陷多边形点集列表（仅 YS/ZW/TJYS/HS 且 polygon 型）。

    每个标注形状=一个缺陷实例样本（不做跨形状连通域合并——忠实于标注员
    的实例划分）。
    """
    try:
        doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: List[np.ndarray] = []
    for s in doc.get("shapes", []):
        if s.get("label") not in DEFECT_LABELS or s.get("shape_type") != "polygon":
            continue
        pts = np.asarray(s.get("points", []), dtype=np.float32)
        if pts.ndim == 2 and pts.shape[0] >= 3 and pts.shape[1] == 2:
            out.append(pts)
    return out


def bbox_of(points: np.ndarray) -> Tuple[float, float, float, float]:
    """多边形点集 → (x1, y1, x2, y2)。"""
    x1, y1 = points.min(axis=0)
    x2, y2 = points.max(axis=0)
    return float(x1), float(y1), float(x2), float(y2)


def split_images(
    files: Sequence[str], seed: int = 42, val_ratio: float = 0.2
) -> Tuple[List[str], List[str]]:
    """确定性按图切分（排序后 seed 洗牌）——输入序不改变结果。"""
    ordered = sorted(files)
    rng = random.Random(seed)
    rng.shuffle(ordered)
    n_val = round(len(ordered) * val_ratio)
    return ordered[n_val:], ordered[:n_val]


def jitter_box(
    bbox: Tuple[float, float, float, float],
    hw: Tuple[int, int],
    rng: np.random.Generator,
    frac: float = 0.10,
) -> Tuple[float, float, float, float]:
    """盒提示抖动：各边 ±frac·边长随机外扩/内缩，中心恒含、贴边裁剪、
    最小边 8px 防退化（模拟用户点击盒的不精确性）。"""
    h, w = hw
    x1, y1, x2, y2 = bbox
    bw, bh = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
    dxa = rng.uniform(0, frac) * bw
    dxb = rng.uniform(0, frac) * bw
    dya = rng.uniform(0, frac) * bh
    dyb = rng.uniform(0, frac) * bh
    jx1, jy1 = x1 - dxa, y1 - dya
    jx2, jy2 = x2 + dxb, y2 + dyb
    jx1 = max(jx1, x1 - frac * bw)
    jy1 = max(jy1, y1 - frac * bh)
    if jx2 - jx1 < 8:
        jx2 = min(jx1 + 8, w - 1)
        jx1 = max(jx2 - 8, 0)
    if jy2 - jy1 < 8:
        jy2 = min(jy1 + 8, h - 1)
        jy1 = max(jy2 - 8, 0)
    return (
        float(max(jx1, 0)), float(max(jy1, 0)),
        float(min(jx2, w - 1)), float(min(jy2, h - 1)),
    )


def flip_aug(points: np.ndarray, hw: Tuple[int, int], horizontal: bool) -> np.ndarray:
    """水平/垂直翻转（点集坐标同步镜像）。"""
    out = points.copy()
    if horizontal:
        out[:, 0] = (hw[1] - 1) - points[:, 0]
    else:
        out[:, 1] = (hw[0] - 1) - points[:, 1]
    return out


def rasterize_polygon(
    points: np.ndarray, out_hw: Tuple[int, int], scale_xy: Tuple[float, float]
) -> np.ndarray:
    """多边形按 (sx, sy) 缩放后栅格化到 out_hw 二值掩码（uint8）。"""
    import cv2

    scaled = points.copy()
    scaled[:, 0] = points[:, 0] * scale_xy[0]
    scaled[:, 1] = points[:, 1] * scale_xy[1]
    m = np.zeros(out_hw, dtype=np.uint8)
    cv2.fillPoly(m, [np.round(scaled).astype(np.int32)], 1)
    return m


def scale_box(
    bbox: Tuple[float, float, float, float],
    from_hw: Tuple[int, int],
    to_hw: Tuple[int, int],
) -> Tuple[float, float, float, float]:
    """盒坐标按两分辨率比例缩放。"""
    x1, y1, x2, y2 = bbox
    sx = to_hw[1] / from_hw[1]
    sy = to_hw[0] / from_hw[0]
    return x1 * sx, y1 * sy, x2 * sx, y2 * sy


def hungarian_single(cost_row: np.ndarray) -> int:
    """单 GT 行的最优查询索引（scipy 匈牙利；退化=argmin）。"""
    return int(np.argmin(cost_row))


def _sigmoid_focal(
    logits: torch.Tensor, targets: torch.Tensor,
    alpha: float = FOCAL_ALPHA, gamma: float = FOCAL_GAMMA,
) -> torch.Tensor:
    p = torch.sigmoid(logits)
    ce = torch.nn.functional.binary_cross_entropy_with_logits(
        logits, targets, reduction="none"
    )
    p_t = p * targets + (1 - p) * (1 - targets)
    loss = ce * ((1 - p_t) ** gamma)
    alpha_t = alpha * targets + (1 - alpha) * (1 - targets)
    return (loss * alpha_t).mean()


def focal_dice_loss(logits: torch.Tensor, gt: torch.Tensor) -> torch.Tensor:
    """focal×20 + soft dice（fp32 域计算）。"""
    logits = logits.float()
    gt = gt.float()
    focal = _sigmoid_focal(logits, gt)
    probs = torch.sigmoid(logits)
    dim = tuple(range(1, probs.dim()))
    inter = (probs * gt).sum(dim=dim)
    union = probs.sum(dim=dim) + gt.sum(dim=dim)
    dice = 1.0 - (2.0 * inter + 1.0) / (union + 1.0)
    return FOCAL_WEIGHT * focal + dice.mean()


def objectness_loss(logits: torch.Tensor, pos_idx: int) -> torch.Tensor:
    """全查询 focal objectness：正查询→1，其余→0（DETR 惯例）。

    ⚠️ v1.1 起训练循环不再调用（1:199 失衡 focal 压塌分布，实测 val
    IoU 0.559→0.000）；保留纯函数与单测作为负结果记录。
    """
    targets = torch.zeros_like(logits.float())
    targets[pos_idx] = 1.0
    return _sigmoid_focal(logits.float(), targets)


# ================================ 数据集 ================================ #


class PoleDefectDataset(torch.utils.data.Dataset):
    """盒提示单实例样本：__getitem__ = (RGB 图, GT 多边形, 抖动盒)。

    初始化时解析全部 JSON（多边形点集，轻量）；图像按需 imread。
    增强：盒抖动 + 随机水平/垂直翻转（点集与盒同步镜像）。
    """

    def __init__(self, data_dir: Path, files: Sequence[str], seed: int = 123):
        sys.path.insert(0, str(REPO_ROOT))
        from core.image_io import imread_unicode

        self._imread = imread_unicode
        self.data_dir = Path(data_dir)
        self.rng = np.random.default_rng(seed)
        self.items: List[Tuple[str, np.ndarray]] = []
        for name in files:
            shapes = extract_defect_shapes(self.data_dir / (Path(name).stem + ".json"))
            for pts in shapes[:6]:  # 每图上限 6 实例（防单图霸榜）
                self.items.append((name, pts))

    def __len__(self) -> int:
        return len(self.items)

    def _imread_retry(self, path: str):
        """三次重试 + gc（v1.0 系统内存耗尽致 cv2 alloc 7MB 失败的硬化）。"""
        import gc

        for attempt in range(3):
            try:
                img = self._imread(path)
                if img is not None:
                    return img
            except Exception:  # noqa: BLE001 — cv2 alloc 异常重试
                pass
            gc.collect()
            time.sleep(2.0)
        raise RuntimeError(f"图像读取失败(3 次重试): {path}")

    def __getitem__(self, idx: int) -> Dict[str, object]:
        name, pts = self.items[idx]
        img = self._imread_retry(str(self.data_dir / name))
        h, w = img.shape[:2]
        pts = pts.copy()
        if self.rng.random() < 0.5:
            pts = flip_aug(pts, (h, w), horizontal=True)
        if self.rng.random() < 0.5:
            pts = flip_aug(pts, (h, w), horizontal=False)
        box = jitter_box(bbox_of(pts), (h, w), self.rng)
        return {
            "image": np.ascontiguousarray(img[..., ::-1]),  # BGR→RGB
            "polygon": pts,
            "box": box,
            "hw": (h, w),
        }


def _collate(batch: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return batch


# ================================ 训练/评估 ================================ #


def build_model(base_dir: Path, device: str) -> Tuple[torch.nn.Module, object]:
    from transformers import Sam3Model, Sam3Processor

    model = Sam3Model.from_pretrained(str(base_dir))
    processor = Sam3Processor.from_pretrained(str(base_dir))
    for p in model.parameters():
        p.requires_grad = False
    n_train = 0
    for mod_name in TRAINABLE_MODULES:
        for p in getattr(model, mod_name).parameters():
            p.requires_grad = True
            n_train += p.numel()
    model.to(device)
    return model, processor


def _forward_box(model, processor, device, batch):
    inputs = processor(
        images=[s["image"] for s in batch],
        input_boxes=[[list(s["box"])] for s in batch],  # (B, 1, 4) 三层深度
        return_tensors="pt",
    )
    inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    out = model(**inputs)
    return out, inputs


def train_one_step(model, processor, batch, opt, scaler, device) -> float:
    """单步：匈牙利匹配 → 正查询 focal+dice 掩码损失（v1.1）。"""
    out, _ = _forward_box(model, processor, device, batch)
    masks = out.pred_masks  # (B, Q, H', W')
    _, _, mh, mw = masks.shape
    total = 0.0
    for i, s in enumerate(batch):
        h, w = s["hw"]
        gt = rasterize_polygon(
            s["polygon"], (mh, mw), (mw / w, mh / h)
        )
        gt_t = torch.from_numpy(gt.astype(np.float32)).to(device).unsqueeze(0)
        m_i = masks[i].float()  # (Q, H', W')
        # 匹配代价：focal + (1-dice)（sigmoid 域，fp32）
        with torch.no_grad():
            probs = m_i.sigmoid()
            gt_flat = gt_t.flatten()
            p_flat = probs.flatten(1)
            inter = (p_flat * gt_flat).sum(1)
            union = p_flat.sum(1) + gt_flat.sum()
            dice = (2.0 * inter + 1.0) / (union + 1.0)
            ce = torch.nn.functional.binary_cross_entropy_with_logits(
                m_i, gt_t.expand_as(m_i), reduction="none"
            ).flatten(1).mean(1)
            cost = ce + (1.0 - dice)
            pos = hungarian_single(cost.cpu().numpy())
        loss = focal_dice_loss(m_i[pos].unsqueeze(0), gt_t)
        total = total + loss
    loss = total / len(batch)
    opt.zero_grad(set_to_none=True)
    scaler.scale(loss).backward()
    scaler.step(opt)
    scaler.update()
    return float(loss.detach())


@torch.no_grad()
def eval_click_iou(model, processor, device, data_dir: Path, files: Sequence[str],
                   limit: int = 40) -> float:
    """val 点击模式 mean IoU（复刻 adapter.predict_point 语义：质心 ±16px
    代偿盒 → post_process(0.3) → 最高分实例 → 全图 IoU）。"""
    sys.path.insert(0, str(REPO_ROOT))
    from core.image_io import imread_unicode

    model.eval()
    ious: List[float] = []
    for name in list(files)[:limit]:
        shapes = extract_defect_shapes(data_dir / (Path(name).stem + ".json"))
        if not shapes:
            continue
        pts = max(shapes, key=lambda p: p.shape[0])
        img = imread_unicode(str(data_dir / name))
        if img is None:
            continue
        h, w = img.shape[:2]
        gt = rasterize_polygon(pts, (h, w), (1.0, 1.0)) > 0
        cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
        r = 16.0
        box = [max(cx - r, 0), max(cy - r, 0), min(cx + r, w - 1), min(cy + r, h - 1)]
        rgb = np.ascontiguousarray(img[..., ::-1])
        inputs = processor(images=rgb, input_boxes=[[[*box]]], return_tensors="pt")
        inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
        out = model(**inputs)
        res = processor.post_process_instance_segmentation(
            out, target_sizes=[(h, w)]
        )[0]
        scores_np = res["scores"].detach().float().cpu().numpy()
        if len(scores_np) == 0:
            ious.append(0.0)
            continue
        best = np.asarray(res["masks"].detach().cpu().numpy()[int(np.argmax(scores_np))])
        inter = np.logical_and(best > 0, gt).sum()
        union = np.logical_or(best > 0, gt).sum()
        ious.append(inter / union if union else 0.0)
    model.train()
    return float(np.mean(ious)) if ious else 0.0


def save_checkpoint(model, processor, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    processor.save_pretrained(str(out_dir))


# ================================ 入口 ================================ #


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SAM3 极柱域微调（W48）")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--val-n", type=int, default=40)
    parser.add_argument("--max-steps", type=int, default=0, help=">0 时截断每 epoch 步数")
    parser.add_argument("--smoke", action="store_true",
                        help="冒烟：3 样本 2 步 + 2 图 val + ckpt 存取 + adapter 复载")
    args = parser.parse_args(argv)

    torch.manual_seed(42)
    np.random.seed(42)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[ft] device={device} base={args.base}")

    import glob as _glob

    files = [
        Path(p).name for p in _glob.glob(str(args.data / "*.bmp"))
        if not Path(p).name.startswith("(")
    ]
    files = [f for f in files if extract_defect_shapes(args.data / (Path(f).stem + ".json"))]
    train_files, val_files = split_images(files)
    print(f"[ft] 缺陷图 {len(files)} → train {len(train_files)} / val {len(val_files)}")

    model, processor = build_model(args.base, device)
    n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[ft] 可训参数 {n_train/1e6:.2f}M（{'+'.join(TRAINABLE_MODULES)}）")

    train_ds = PoleDefectDataset(args.data, train_files)
    print(f"[ft] 训练样本（组件）{len(train_ds)}")

    if args.smoke:
        args.out = args.out.with_name(args.out.name + "-smoke")
        args.epochs, args.max_steps, args.val_n = 1, 2, 2

    loader = torch.utils.data.DataLoader(
        train_ds, batch_size=args.batch, shuffle=True,
        collate_fn=_collate, num_workers=0,
    )
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr
    )
    scaler = torch.amp.GradScaler(enabled=(device == "cuda"))
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, T_max=max(args.epochs, 1)
    )

    history: List[Dict[str, float]] = []
    best_iou = -1.0
    aborted = False
    model.train()
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        losses: List[float] = []
        for step, batch in enumerate(loader, 1):
            losses.append(train_one_step(model, processor, batch, opt, scaler, device))
            # 塌缩护栏：每 200 步 mini-val（基线 ~0.5；<0.05 即塌损坏）
            if step % 200 == 0 and not args.max_steps:
                mini = eval_click_iou(
                    model, processor, device, args.data, val_files, 10
                )
                print(f"[ft]   step {step} mini-val IoU={mini:.3f}", flush=True)
                if step >= 400 and mini < 0.05:
                    print("[ft] 塌缩护栏触发（mini-val < 0.05），中止训练", flush=True)
                    aborted = True
                    break
            if args.max_steps and step >= args.max_steps:
                break
        val_iou = eval_click_iou(
            model, processor, device, args.data, val_files, args.val_n
        )
        sched.step()
        history.append({
            "epoch": epoch,
            "train_loss": float(np.mean(losses)),
            "val_click_iou": val_iou,
            "seconds": round(time.time() - t0, 1),
        })
        peak = (torch.cuda.max_memory_allocated() / 1e9) if device == "cuda" else 0.0
        print(
            f"[ft] epoch {epoch}/{args.epochs} loss={history[-1]['train_loss']:.4f} "
            f"val_click_IoU={val_iou:.3f} ({history[-1]['seconds']}s, peak {peak:.2f}GB)",
            flush=True,
        )
        if aborted:
            break
        if val_iou > best_iou:
            best_iou = val_iou
            save_checkpoint(model, processor, args.out)
            print(f"[ft] 最优 ckpt 已存 {args.out}（IoU={val_iou:.3f}）", flush=True)

    (args.out / "manifest.json").write_text(
        json.dumps({"train": train_files, "val": val_files}, ensure_ascii=False),
        encoding="utf-8",
    )
    (args.out / "history.json").write_text(
        json.dumps({"history": history, "best_val_click_iou": best_iou}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[ft] {'中止' if aborted else '完成'}：best val_click_IoU={best_iou:.3f} → {args.out}", flush=True)

    if args.smoke:
        # ckpt 经真实 adapter 复载验证（与验收同路径）
        sys.path.insert(0, str(REPO_ROOT))
        from labeling.sam3_adapter import Sam3Adapter

        adapter = Sam3Adapter()
        adapter.load(str(args.out), device=device)
        img = train_ds[0]["image"]
        box = train_ds[0]["box"]
        poly = adapter.predict_box(img, box)
        print(f"[ft][smoke] adapter 复载 OK，predict_box 折点={len(poly)}")
        assert adapter.loaded
    return 0


if __name__ == "__main__":
    sys.exit(main())
