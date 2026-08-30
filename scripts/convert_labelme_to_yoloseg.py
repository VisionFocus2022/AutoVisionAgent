"""LabelMe → YOLO-seg 数据转换（W50 · docs/prd-pole-seg-model.md FR-1）。

切分严格复用 W48 manifest（weights/sam3-pole-ft/manifest.json——同口径
验收铁律：val 162 缺陷图与 SAM3 验收完全同集）；368 背景图全进 train
（空标签防误检，不入 val）。图像复制至 dataset_yoloseg/images/{train,val}
（ultralytics images/labels 倒数二级目录路径约定）。

用法：
    .venv/Scripts/python.exe scripts/convert_labelme_to_yoloseg.py \
        [--data E:/学习项目/极柱外观检标注图] [--out dataset_yoloseg]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "weights" / "sam3-pole-ft" / "manifest.json"

DEFECT_LABELS = {"YS", "ZW", "TJYS", "HS"}
N_CLASSES = 1
CLASS_ID = 0  # 单类 defect（四缺陷标签合单类）


# ---------------------------- 纯函数（单测面） ---------------------------- #


def polygon_to_yolo_line(points: list[list[float]], img_w: int, img_h: int) -> str | None:
    """LabelMe 多边形点 → YOLO-seg 归一化行 `0 x1 y1 x2 y2 ...`。

    坐标越界裁剪到 [0,1]；<3 点返回 None（YOLO 拒收）。
    """
    if len(points) < 3:
        return None
    vals: list[float] = []
    for x, y in points:
        vals.append(min(max(x / img_w, 0.0), 1.0))
        vals.append(min(max(y / img_h, 0.0), 1.0))
    return str(CLASS_ID) + " " + " ".join(f"{v:.6f}" for v in vals)


def labelme_to_lines(json_path: Path, img_w: int, img_h: int) -> list[str]:
    """LabelMe JSON → YOLO-seg 标签行列表（缺陷多边形，单类）。"""
    try:
        doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lines: list[str] = []
    for s in doc.get("shapes", []):
        if s.get("label") not in DEFECT_LABELS or s.get("shape_type") != "polygon":
            continue
        line = polygon_to_yolo_line(s.get("points", []), img_w, img_h)
        if line:
            lines.append(line)
    return lines


def read_image_size(bmp_path: Path) -> tuple[int, int] | None:
    """BMP 尺寸（免整图解码：BFM 头 DIB 段宽高）。"""
    try:
        with open(bmp_path, "rb") as f:
            header = f.read(26)
        if len(header) < 26 or header[:2] != b"BM":
            return None
        import struct

        w, h = struct.unpack("<ii", header[18:26])
        return abs(w), abs(h)  # h<0 = top-down 位图
    except OSError:
        return None


def write_data_yaml(out_dir: Path) -> Path:
    """data.yaml（单类 + 绝对路径 train/val 目录）。"""
    yaml_path = out_dir / "data.yaml"
    content = (
        f"path: {out_dir.resolve().as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        f"nc: {N_CLASSES}\n"
        "names: ['defect']\n"
    )
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


# ---------------------------- 主流程 ---------------------------- #


def convert(data_dir: Path, out_dir: Path, manifest: Path) -> dict:
    """执行转换，返回统计 {train_defect, train_bg, val_defect, lines}。"""
    man = json.loads(Path(manifest).read_text(encoding="utf-8"))
    stats = {"train_defect": 0, "train_bg": 0, "val_defect": 0, "lines": 0}

    for split in ("train", "val"):
        (out_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    # 缺陷图按 manifest 切分（同口径铁律）
    for split, names in (("train", man["train"]), ("val", man["val"])):
        for name in names:
            bmp = data_dir / name
            jp = data_dir / (Path(name).stem + ".json")
            size = read_image_size(bmp)
            if size is None:
                print(f"[convert] 跳过（尺寸读取失败）: {name}", flush=True)
                continue
            w, h = size
            lines = labelme_to_lines(jp, w, h)
            shutil.copy2(bmp, out_dir / "images" / split / name)
            (out_dir / "labels" / split / (Path(name).stem + ".txt")).write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )
            stats[f"{split}_defect"] += 1
            stats["lines"] += len(lines)

    # 背景图（有 json 但无缺陷多边形，或 (N) 前缀正常图）全进 train、空标签
    for jp in sorted(data_dir.glob("*.json")):
        name = jp.with_suffix(".bmp").name
        if (out_dir / "images" / "val" / name).exists():
            continue  # 已入 val 的缺陷图不重复
        if (out_dir / "images" / "train" / name).exists():
            continue
        bmp = data_dir / name
        if not bmp.exists():
            continue
        try:
            doc = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {"shapes": []}
        has_defect = any(
            s.get("label") in DEFECT_LABELS and s.get("shape_type") == "polygon"
            for s in doc.get("shapes", [])
        )
        if has_defect and name in set(man["train"]) | set(man["val"]):
            continue
        if has_defect:
            # manifest 外的缺陷图（如 extract 不通过的边缘态）不入 train 防口径污染
            continue
        shutil.copy2(bmp, out_dir / "images" / "train" / name)
        (out_dir / "labels" / "train" / (Path(name).stem + ".txt")).write_text(
            "", encoding="utf-8"
        )
        stats["train_bg"] += 1

    write_data_yaml(out_dir)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LabelMe → YOLO-seg 转换（W50）")
    parser.add_argument("--data", type=Path,
                        default=Path(r"E:/学习项目/极柱外观检标注图"))
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "dataset_yoloseg")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    stats = convert(args.data, args.out, args.manifest)
    print(f"[convert] {stats}")
    print(f"[convert] data.yaml -> {args.out / 'data.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
