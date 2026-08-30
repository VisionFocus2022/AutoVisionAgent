"""极柱专用 YOLO-seg 训练（W50 · docs/prd-pole-seg-model.md FR-2）。

yolov8n-seg 预训练微调（单类 defect），数据 = dataset_yoloseg（转换脚本
产物，切分复用 W48 manifest 保同口径验收）。产物 weights/pole-seg/best.pt。

用法：
    .venv/Scripts/python.exe scripts/train_pole_seg.py [--epochs 60] [--imgsz 1280]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PRETRAINED = REPO_ROOT / "yolov8n-seg.pt"
DATA_YAML = REPO_ROOT / "dataset_yoloseg" / "data.yaml"
OUT_DIR = REPO_ROOT / "weights" / "pole-seg"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="极柱专用 YOLO-seg 训练（W50/W51）")
    parser.add_argument("--model", default="yolov8n-seg.pt",
                        help="预训练权重（yolov8s-seg.pt 等自动下载）")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--batch", type=float, default=0.6, help="ultralytics 显存自适应分数")
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None,
                        help="产物目录（默认 weights/pole-seg-<model>-<imgsz>）")
    args = parser.parse_args(argv)

    if not DATA_YAML.is_file():
        print(f"[train] 缺数据集配置: {DATA_YAML}（先跑 convert_labelme_to_yoloseg.py）")
        return 2

    from ultralytics import YOLO

    if args.out is None:
        tag = Path(args.model).stem
        args.out = REPO_ROOT / "weights" / f"pole-seg-{tag}-{args.imgsz}"
    model = YOLO(args.model)  # 缺权重自动下载
    OUT_DIR = args.out  # W51 事故修正：参数化时本行被 no-op replace 吞掉，
    # 致 s@1600 产物覆盖 n 模型目录（n best.pt 丢失，数字已留档）
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        project=str(OUT_DIR.parent),
        name=OUT_DIR.name,
        exist_ok=True,
        seed=42,
        workers=4,
        device=0,
        # 微缺陷增强：保守 mosaic/翻转，关大角度旋转（缺陷形态敏感）
        flipud=0.0,
        degrees=0.0,
        scale=0.2,
    )
    best = OUT_DIR / "weights" / "best.pt"
    print(f"[train] 完成 best={best} 存在={best.is_file()}")
    return 0 if best.is_file() else 1


if __name__ == "__main__":
    sys.exit(main())
