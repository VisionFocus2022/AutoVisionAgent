"""全局常量定义（消除重复 + 统一一致性）。"""
from __future__ import annotations

import os
from pathlib import Path

# ============================== 图像扩展名 ============================== #
# 所有模块共用同一份定义，避免 .webp 不一致 bug
IMG_EXTS: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".bmp",
    ".tif", ".tiff", ".webp",
)

# 标注 JSON 扩展名
ANN_EXTS: tuple[str, ...] = (".json",)

# ============================== 路径常量 ============================== #
# 项目根目录（向上回溯到仓库根）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# configs 目录
CONFIG_DIR = _PROJECT_ROOT / "configs"

# 默认项目存储根目录
DEFAULT_PROJECT_ROOT = os.path.expanduser("~/AutoVisionAgent_Projects")


__all__ = [
    "IMG_EXTS",
    "ANN_EXTS",
    "CONFIG_DIR",
    "DEFAULT_PROJECT_ROOT",
]
