"""全局常量定义（消除重复 + 统一一致性）。"""
from __future__ import annotations

import os
import shutil
import sys
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

# W68：用户/机器态配置目录——冻结 exe 下 PyInstaller 重建会清空整个
# dist 目录（users.json/审计/历史/设置随葬，密码反复重置的根因），故
# 解析到 %APPDATA% 持久目录；源码模式维持仓根 configs（开发现状不变）。
_USER_STATE_FILES = (
    "users.json",
    "initial_credentials.txt",
    "user_settings.json",
    "license.key",
)


def _resolve_config_dir() -> Path:
    """配置目录解析：冻结态 %APPDATA%（重建/重装不丢），源码态仓根 configs。"""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(
            Path.home() / "AppData" / "Roaming"
        )
        return Path(base) / "AutoVisionAgent" / "configs"
    return _PROJECT_ROOT / "configs"


def migrate_legacy_configs() -> list[str]:
    """W68 冻结首启迁移：把随包 _internal/configs 的旧用户态文件搬到
    持久目录（当前密码/许可证无缝衔接）。目标已存在不覆盖（保护新数据）；
    非冻结态零操作。返回迁移的文件名列表。"""
    if not getattr(sys, "frozen", False):
        return []
    legacy = Path(getattr(sys, "_MEIPASS", "")) / "configs"
    if not legacy.is_dir():
        return []
    migrated: list[str] = []
    for name in _USER_STATE_FILES:
        src = legacy / name
        dst = _resolve_config_dir() / name
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            migrated.append(name)
    return migrated


CONFIG_DIR = _resolve_config_dir()

# 默认项目存储根目录
# W28：调用期展开形态（~/…）供 project.paths.resolve_base_root 使用——
# 不得在导入期预展开后消费（os.path.expanduser 的测试接缝须在调用期生效）
DEFAULT_PROJECT_ROOT_TILDE = "~/AutoVisionAgent_Projects"
DEFAULT_PROJECT_ROOT = os.path.expanduser(DEFAULT_PROJECT_ROOT_TILDE)


__all__ = [
    "IMG_EXTS",
    "ANN_EXTS",
    "CONFIG_DIR",
    "DEFAULT_PROJECT_ROOT",
    "DEFAULT_PROJECT_ROOT_TILDE",
    "migrate_legacy_configs",
]
