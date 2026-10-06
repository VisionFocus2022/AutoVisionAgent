"""LabelMe → YOLO/COCO 训练集导出（W5-T2，supervision 方法文章落地）。

补齐"标注 → 训练"断链：标注页存 LabelMe JSON，ultralytics 等训练框架
需要 YOLO txt / COCO json。纯函数、无 Qt 依赖，可被 GUI worker 或脚本调用。

规则：
- 类别名按字典序稳定排序 → 类别 id（与 sv_bridge 的 class_id 映射一致）
- rectangle → YOLO 检测行 ``cls cx cy w h``（按 imageWidth/Height 归一化）
- polygon  → YOLO 分割行 ``cls x1 y1 x2 y2 ...``（归一化）
- COCO：矩形 bbox=xywh 绝对坐标 + 多边形 segmentation；category_id 从 1 起
- 坏 JSON / 找不到图像 → 跳过并计数（返回摘要含 skipped）
- train/val 分层划分（P0-1，2026-10-05 二轮审查 R1）：按类别分层随机
  划分（默认 8:2，val_ratio 参数可调），消除 train=val 同目录导致的
  "mAP 在训练集上计算、指标虚高"问题；stem 冲突检测防静默覆盖
"""
from __future__ import annotations

import json
import logging
import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# P0-1：默认验证集比例（0.2 = 8:2）；train/val 目录名与 ultralytics 惯例一致
_DEFAULT_VAL_RATIO = 0.2


@dataclass(frozen=True)
class ExportSummary:
    """导出摘要（不可变）。P0-1 起含 train/val 划分计数。"""

    classes: tuple[str, ...]
    images: int
    labels: int
    skipped: int
    train_images: int = 0
    val_images: int = 0


def _load_docs(annotation_dir: str) -> tuple[list[dict], int]:
    """读取目录内全部 LabelMe JSON，坏文件跳过计数。"""
    docs: list[dict] = []
    skipped = 0
    for p in sorted(Path(annotation_dir).glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or "shapes" not in doc:
                raise ValueError("非 LabelMe 结构")
            docs.append(doc)
        except (json.JSONDecodeError, OSError, ValueError):
            skipped += 1
            logger.warning("跳过无效标注文件: %s", p)
    return docs, skipped


def _resolve_image(doc: dict, image_dir: str, annotation_dir: str) -> Path:
    """按 imagePath 定位图像（标注目录优先，其次图像目录）。

    P0-1（O4 防御）：imagePath 为空时 ``base / ""`` 等于 base 目录本身且
    exists() 恒真——返回目录会让后续 copy2(目录) 崩溃。此处校验 name
    非空且候选为文件才返回。
    """
    name = Path(str(doc.get("imagePath", ""))).name
    if not name:
        raise FileNotFoundError("(empty imagePath)")
    for base in (Path(annotation_dir), Path(image_dir)):
        cand = base / name
        if cand.is_file():
            return cand
    raise FileNotFoundError(name)


def _normalize_pt(x: float, y: float, w: int, h: int) -> tuple[float, float]:
    return (min(max(x / w, 0.0), 1.0), min(max(y / h, 0.0), 1.0))


def _stratified_split(
    docs: list[dict], val_ratio: float, seed: int
) -> dict[str, str]:
    """P0-1：按类别分层随机划分 docs → {图像名: "train"|"val"}。

    分层策略：以每张图的类别元组（排序后）为分层键，各层内部按
    val_ratio 随机抽 val——保证稀有缺陷类别在 val 集不缺席（工业
    小数据集关键）。单样本层（该类别组合仅 1 张）优先分给 train，
    保证稀有类别至少参与训练。

    Returns:
        {image 文件名: 子集名}。val_ratio<=0 时全 train。
    """
    if val_ratio <= 0:
        return {}
    rng = random.Random(seed)

    # 按类别组合分桶
    buckets: dict[tuple[str, ...], list[str]] = {}
    for doc in docs:
        key = tuple(sorted({s["label"] for s in doc["shapes"] if s.get("label")}))
        name = Path(str(doc.get("imagePath", ""))).name
        buckets.setdefault(key, []).append(name)

    assignment: dict[str, str] = {}
    for key in sorted(buckets):
        names = sorted(buckets[key])
        n_val = round(len(names) * val_ratio)
        # 单样本层优先给 train：稀有类别至少参与训练（val 全缺某类
        # 时 mAP 该类为 NaN，训练缺类则模型根本学不到）
        if len(names) == 1 or n_val == 0:
            for name in names:
                assignment[name] = "train"
            continue
        rng.shuffle(names)
        for i, name in enumerate(names):
            assignment[name] = "val" if i < n_val else "train"
    return assignment


def _shapes_to_yolo_lines(
    doc: dict, cls_id: dict[str, int], w: int, h: int
) -> list[str]:
    """单条 LabelMe 标注 → YOLO 行列表（W24 规模拆分，自主函数抽出）。

    rectangle → ``cls cx cy bw bh``（M4：clamp 到 [0,1]）；其余 shape →
    归一化分割行。与主流程同逻辑，零行为变更。
    """
    lines: list[str] = []
    for s in doc["shapes"]:
        label = s.get("label")
        if label not in cls_id or len(s.get("points", [])) < 2:
            continue
        pts = s["points"]
        if s.get("shape_type") == "rectangle":
            (x1, y1), (x2, y2) = pts[0], pts[1]
            cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
            bw, bh = abs(x2 - x1) / w, abs(y2 - y1) / h
            # P0-1（M4）：矩形分支补 clamp（polygon 分支已有 _normalize_pt）
            cx, cy = min(max(cx, 0.0), 1.0), min(max(cy, 0.0), 1.0)
            bw, bh = min(max(bw, 0.0), 1.0), min(max(bh, 0.0), 1.0)
            lines.append(f"{cls_id[label]} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        else:  # polygon / polyline → 分割行
            flat = []
            for x, y in pts:
                nx, ny = _normalize_pt(float(x), float(y), w, h)
                flat += [f"{nx:.6f}", f"{ny:.6f}"]
            lines.append(f"{cls_id[label]} " + " ".join(flat))
    return lines


def _prepare_split_dirs(out: Path, docs: list[dict], val_ratio: float, seed: int) -> dict[str, str]:
    """P0-1：划分决策 + 目录准备（W24 规模拆分，自 labelme_dir_to_yolo 抽出）。

    - 分层划分（_stratified_split）+ 空 val 兜底（从 train 挪 1 张）；
    - 创建 images/{train,val} 与 labels/{train,val} 子目录；
    - 返回 {图像名: 子集名}；val_ratio<=0 返回 {}（调用方退化到旧单目录）。
    """
    if val_ratio <= 0:
        return {}
    split = _stratified_split(docs, val_ratio, seed)
    # 兜底：所有类别桶都是单样本（小数据集）时 val 可能为空——空 val
    # 目录会让 ultralytics 训练直接报错。从 train 挪 1 张（sorted 首张，
    # 确定性）保证 val 非空；指标至少基于 1 张 held-out。
    if not any(v == "val" for v in split.values()) and len(split) >= 2:
        first = min(n for n, v in split.items() if v == "train")
        split[first] = "val"
        logger.warning(
            "数据集过小（类别桶均为单样本），val 集由 train 挪 1 张"
            "兜底 (%s)——验证指标统计意义有限，建议扩充数据", first,
        )
    (out / "images" / "train").mkdir(exist_ok=True)
    (out / "images" / "val").mkdir(exist_ok=True)
    (out / "labels" / "train").mkdir(exist_ok=True)
    (out / "labels" / "val").mkdir(exist_ok=True)
    return split


def candidate_label_dirs(train_dir: str) -> list[str]:
    """train 图像目录 → 候选 labels 目录（P0-1 划分与旧平铺双兼容，W1-1 批）。

    导出布局由本模块定义，布局逆向定位（训练页任务探测用）同源放此。
    """
    if not train_dir:
        return []
    d = os.path.normpath(train_dir)
    parent = os.path.dirname(d)
    return [
        os.path.join(parent, "labels"),                    # images/ → ../labels（旧平铺）
        os.path.join(parent, "labels", "train"),           # images/ → ../labels/train（P0-1）
        os.path.join(d, "labels"),                         # 根目录就地（旧）
        os.path.join(d, "labels", "train"),                # 根目录就地 train（P0-1）
        os.path.join(os.path.dirname(parent), "labels", "train"),  # images/train → ../../labels/train
    ]


def label_txt_files(labels_dir: str) -> list[str]:
    """labels 目录（平铺或含 train 子目录）→ 排序后的 txt 全路径。"""
    for d in (labels_dir, os.path.join(labels_dir, "train")):
        if os.path.isdir(d):
            files = [os.path.join(d, n) for n in sorted(os.listdir(d))
                     if n.endswith(".txt")]
            if files:
                return files
    return []


def labelme_dir_to_yolo(
    image_dir: str,
    annotation_dir: str,
    out_dir: str,
    val_ratio: float = _DEFAULT_VAL_RATIO,
    seed: int = 42,
) -> ExportSummary:
    """LabelMe 目录 → YOLO 格式（images/{train,val} + labels/{train,val} + data.yaml）。

    P0-1（2026-10-05 二轮审查 R1）：此前 train/val 写死同一 images 目录，
    mAP 实际在训练集上计算，指标虚高。现按类别分层划分（默认 8:2，
    val_ratio 可调；val_ratio=0 时保持全 train 单目录，兼容旧行为）。

    Args:
        val_ratio: 验证集比例（0~1）；<=0 时不分 val（全 train）。
        seed: 划分随机种子（默认 42，可复现）。
    """
    docs, skipped = _load_docs(annotation_dir)
    if not docs:
        raise ValueError(f"无有效 LabelMe 标注文件: {annotation_dir}")

    classes = sorted({s["label"] for d in docs for s in d["shapes"] if s.get("label")})
    cls_id: dict[str, int] = {c: i for i, c in enumerate(classes)}

    out = Path(out_dir)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)

    # P0-1：分层划分；全 train 时退化到旧单目录布局
    split = _prepare_split_dirs(out, docs, val_ratio, seed)

    # P0-1（O5）：stem 索引——同名 stem 的图像在 train/val 子目录下会
    # 静默互相覆盖（a.jpg 与 a.png、或跨目录同名）。检测到即跳过并计数。
    seen_stems: set[str] = set()

    images = labels = train_images = val_images = 0
    for doc in docs:
        try:
            img_path = _resolve_image(doc, image_dir, annotation_dir)
        except FileNotFoundError:
            skipped += 1
            continue
        w = int(doc.get("imageWidth", 0))
        h = int(doc.get("imageHeight", 0))
        if w <= 0 or h <= 0:
            skipped += 1
            continue

        stem = img_path.stem
        if stem in seen_stems:
            skipped += 1
            logger.warning(
                "stem 冲突跳过（同名将静默覆盖）: %s", img_path.name
            )
            continue
        seen_stems.add(stem)

        lines = _shapes_to_yolo_lines(doc, cls_id, w, h)

        subset = split.get(img_path.name, "train")
        if split:
            img_dest = out / "images" / subset / img_path.name
            lbl_dest = out / "labels" / subset / f"{stem}.txt"
        else:
            img_dest = out / "images" / img_path.name
            lbl_dest = out / "labels" / f"{stem}.txt"
        shutil.copy2(img_path, img_dest)
        lbl_dest.write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
        images += 1
        labels += len(lines)
        if subset == "val":
            val_images += 1
        else:
            train_images += 1

    names_block = "\n".join(
        f"  {i}: {c}" for i, c in enumerate(classes)
    )
    # P0-1：data.yaml 指向 train/val 子目录（ultralytics 相对 path 解析）
    yaml_train = "images/train" if split else "images"
    yaml_val = "images/val" if split else "images"
    (out / "data.yaml").write_text(
        f"path: {out.resolve().as_posix()}\n"
        f"train: {yaml_train}\nval: {yaml_val}\n"
        f"nc: {len(classes)}\n"
        f"names:\n{names_block}\n",
        encoding="utf-8",
    )
    return ExportSummary(
        classes=tuple(classes),
        images=images,
        labels=labels,
        skipped=skipped,
        train_images=train_images,
        val_images=val_images,
    )


def labelme_dir_to_coco(
    image_dir: str, annotation_dir: str, out_json: str
) -> ExportSummary:
    """LabelMe 目录 → COCO 检测/分割标注 json。"""
    docs, skipped = _load_docs(annotation_dir)
    if not docs:
        raise ValueError(f"无有效 LabelMe 标注文件: {annotation_dir}")

    classes = sorted({s["label"] for d in docs for s in d["shapes"] if s.get("label")})
    cat_id = {c: i + 1 for i, c in enumerate(classes)}  # COCO 从 1 起

    images: list[dict] = []
    annotations: list[dict] = []
    img_id = ann_id = 0
    for doc in docs:
        try:
            img_path = _resolve_image(doc, image_dir, annotation_dir)
        except FileNotFoundError:
            skipped += 1
            continue
        w = int(doc.get("imageWidth", 0))
        h = int(doc.get("imageHeight", 0))
        if w <= 0 or h <= 0:
            skipped += 1
            continue

        img_id += 1
        images.append(
            {"id": img_id, "file_name": img_path.name, "width": w, "height": h}
        )
        for s in doc["shapes"]:
            label = s.get("label")
            if label not in cat_id or len(s.get("points", [])) < 2:
                continue
            pts = [(float(x), float(y)) for x, y in s["points"]]
            ann_id += 1
            ann: dict = {
                "id": ann_id,
                "image_id": img_id,
                "category_id": cat_id[label],
                "iscrowd": 0,
            }
            if s.get("shape_type") == "rectangle":
                (x1, y1), (x2, y2) = pts[0], pts[1]
                bx, by = min(x1, x2), min(y1, y2)
                bw, bh = abs(x2 - x1), abs(y2 - y1)
                ann["bbox"] = [bx, by, bw, bh]
                ann["area"] = bw * bh
            else:
                flat = [v for pt in pts for v in pt]
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                bx, by = min(xs), min(ys)
                bw, bh = max(xs) - bx, max(ys) - by
                ann["segmentation"] = [flat]
                ann["bbox"] = [bx, by, bw, bh]
                ann["area"] = bw * bh
            annotations.append(ann)

    out = Path(out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "images": images,
                "annotations": annotations,
                "categories": [
                    {"id": i + 1, "name": c, "supercategory": "defect"}
                    for i, c in enumerate(classes)
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return ExportSummary(
        classes=tuple(classes),
        images=len(images),
        labels=len(annotations),
        skipped=skipped,
    )


__all__ = ["ExportSummary", "labelme_dir_to_coco", "labelme_dir_to_yolo"]
