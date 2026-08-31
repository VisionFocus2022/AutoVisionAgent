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

# 权重目录（SAM3 约定发现基准：源码=仓库根/weights，frozen exe=_internal/weights）
WEIGHTS_DIR = _PROJECT_ROOT / "weights"

# 默认项目存储根目录
# W28：调用期展开形态（~/…）供 project.paths.resolve_base_root 使用——
# 不得在导入期预展开后消费（os.path.expanduser 的测试接缝须在调用期生效）
DEFAULT_PROJECT_ROOT_TILDE = "~/AutoVisionAgent_Projects"
DEFAULT_PROJECT_ROOT = os.path.expanduser(DEFAULT_PROJECT_ROOT_TILDE)


__all__ = [
    "IMG_EXTS",
    "ANN_EXTS",
    "CONFIG_DIR",
    "WEIGHTS_DIR",
    "DEFAULT_PROJECT_ROOT",
    "DEFAULT_PROJECT_ROOT_TILDE",
]
