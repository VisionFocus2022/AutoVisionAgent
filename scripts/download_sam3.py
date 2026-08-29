"""下载 SAM3 权重（ModelScope 镜像 facebook/sam3，transformers 格式）。

仅拉取 transformers 推理所需文件（config/processor/tokenizer/model.safetensors，
约 3.5GB），排除原始格式 sam3.pt（另 3.45GB，本项目运行时不用官方 sam3 包）。

HF 原仓 facebook/sam3 为 gated（需申请）；ModelScope 镜像免申请直下。

用法：
    .venv/Scripts/python.exe scripts/download_sam3.py [--dest weights/sam3]

依赖：pip install modelscope（仅下载工具，非项目运行时依赖）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = REPO_ROOT / "weights" / "sam3"

# transformers from_pretrained 所需最小文件集（缺一不可）
REQUIRED_FILES = (
    "config.json",
    "model.safetensors",
    "processor_config.json",
    "tokenizer.json",
)
# 可选但建议随仓的完整性文件
EXTRA_FILES = (
    "configuration.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.json",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载 SAM3 权重（ModelScope 镜像）")
    parser.add_argument(
        "--dest", type=Path, default=DEFAULT_DEST, help="目标目录（默认 weights/sam3）"
    )
    args = parser.parse_args(argv)
    dest: Path = args.dest

    try:
        from modelscope import snapshot_download
    except ImportError:
        print("[ERROR] modelscope 未安装：.venv/Scripts/python.exe -m pip install modelscope")
        return 2

    print(f"[download] facebook/sam3 -> {dest}")
    snapshot_download(
        "facebook/sam3",
        local_dir=str(dest),
        ignore_patterns=["sam3.pt", ".gitattributes", "LICENSE"],
    )

    missing = [name for name in REQUIRED_FILES if not (dest / name).is_file()]
    if missing:
        print(f"[ERROR] 必需文件缺失: {missing}")
        return 1

    total = sum(
        f.stat().st_size for f in dest.iterdir() if f.is_file()
    )
    for name in (*REQUIRED_FILES, *EXTRA_FILES):
        p = dest / name
        if p.is_file():
            print(f"  ok {name:28} {p.stat().st_size:>14,} B")
    print(f"[done] 目录合计 {total / 1e9:.2f} GB，必需文件齐备")
    return 0


if __name__ == "__main__":
    sys.exit(main())
