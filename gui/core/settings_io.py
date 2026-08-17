"""user_settings.json 单一访问器（W13 C1 收敛）。

历史：gui/main._load_user_settings 与 gui/pages/settings/page 各自手写
JSON 读写（路径解析重复）；且设置页写入的 device 无人回读——predict 页
恒读 core.config dataclass 默认 "cuda"，设置页选 CPU 静默失效（P1-2）。

收敛后：加载/保存/设备查询统一走本模块。路径默认 core.constants.CONFIG_DIR，
测试可注入本模块级 CONFIG_DIR（沿用 settings 页 _CONFIG_DIR 注入模式），
或经 config_dir 参数显式传入。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Union

from core.constants import CONFIG_DIR

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "user_settings.json"

#: 设置页可持久化的合法设备键（与 settings 页 _device_keys 一致）
_VALID_DEVICES = ("cuda", "cpu")


def _resolve_dir(config_dir: Optional[Union[str, "os.PathLike[str]"]]) -> str:
    """解析配置目录：显式参数优先，缺省用模块级 CONFIG_DIR（可测试注入）。"""
    return str(config_dir) if config_dir is not None else str(CONFIG_DIR)


def load_user_settings(
    config_dir: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> Dict[str, Any]:
    """加载 user_settings.json；缺失/坏 JSON/非字典 → {}（代码默认值兜底）。"""
    path = os.path.join(_resolve_dir(config_dir), SETTINGS_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.debug("user_settings.json 不可用（%s），使用默认值", exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_user_settings(
    settings: Dict[str, Any],
    config_dir: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> str:
    """保存 user_settings.json（UTF-8 · ensure_ascii=False · indent=2）。

    返回写入路径；目录不存在时自动创建。IO 异常上抛，由调用方决定 UI 反馈。
    """
    resolved = _resolve_dir(config_dir)
    os.makedirs(resolved, exist_ok=True)
    path = os.path.join(resolved, SETTINGS_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    return path


def get_device(
    config_dir: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> Optional[str]:
    """读取用户持久化推理设备。

    未设置 / 非法值 / 文件不可用 → None，调用方走自身默认链
    （predict 页：None → "cuda" → torch.cuda.is_available() 回退）。
    """
    device = load_user_settings(config_dir).get("device")
    if isinstance(device, str) and device in _VALID_DEVICES:
        return device
    return None


__all__ = [
    "SETTINGS_FILENAME",
    "load_user_settings",
    "save_user_settings",
    "get_device",
]
