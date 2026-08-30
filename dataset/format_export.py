"""LabelMe → YOLO/COCO 训练集导出（W5-T2，supervision 方法文章落地）。

补齐"标注 → 训练"断链：标注页存 LabelMe JSON，ultralytics 等训练框架
需要 YOLO txt / COCO json。纯函数、无 Qt 依赖，可被 GUI worker 或脚本调用。

规则：
- 类别名按字典序稳定排序 → 类别 id（与 sv_bridge 的 class_id 映射一致）
- rectangle → YOLO 检测行 ``cls cx cy w h``（按 imageWidth/Height 归一化）
- polygon  → YOLO 分割行 ``cls x1 y1 x2 y2 ...``（归一化）
- COCO：矩形 bbox=xywh 绝对坐标 + 多边形 segmentation；category_id 从 1 起
- 坏 JSON / 找不到图像 → 跳过并计数（返回摘要含 skipped）
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportSummary:
    """导出摘要（不可变）。"""

    classes: tuple[str, ...]
    images: int
    labels: int
    skipped: int


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
    """按 imagePath 定位图像（标注目录优先，其次图像目录）。"""
    name = Path(str(doc.get("imagePath", ""))).name
    for base in (Path(annotation_dir), Path(image_dir)):
        cand = base / name
        if cand.exists():
            return cand
    raise FileNotFoundError(name)


def _normalize_pt(x: float, y: float, w: int, h: int) -> tuple[float, float]:
    return (min(max(x / w, 0.0), 1.0), min(max(y / h, 0.0), 1.0))


def labelme_dir_to_yolo(
    image_dir: str, annotation_dir: str, out_dir: str
) -> ExportSummary:
    """LabelMe 目录 → YOLO 格式（images/ + labels/ + data.yaml）。"""
    docs, skipped = _load_docs(annotation_dir)
    if not docs:
        raise ValueError(f"无有效 LabelMe 标注文件: {annotation_dir}")

    classes = sorted({s["label"] for d in docs for s in d["shapes"] if s.get("label")})
    cls_id: dict[str, int] = {c: i for i, c in enumerate(classes)}

    out = Path(out_dir)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)

    images = labels = 0
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
                lines.append(f"{cls_id[label]} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
            else:  # polygon / polyline → 分割行
                flat = []
                for x, y in pts:
                    nx, ny = _normalize_pt(float(x), float(y), w, h)
                    flat += [f"{nx:.6f}", f"{ny:.6f}"]
                lines.append(f"{cls_id[label]} " + " ".join(flat))

        stem = img_path.stem
        shutil.copy2(img_path, out / "images" / img_path.name)
        (out / "labels" / f"{stem}.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
        images += 1
        labels += len(lines)

    names_block = "\n".join(
        f"  {i}: {c}" for i, c in enumerate(classes)
    )
    (out / "data.yaml").write_text(
        f"path: {out.resolve().as_posix()}\n"
        f"train: images\nval: images\n"
        f"nc: {len(classes)}\n"
        f"names:\n{names_block}\n",
        encoding="utf-8",
    )
    return ExportSummary(
        classes=tuple(classes), images=images, labels=labels, skipped=skipped
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
