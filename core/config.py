"""统一配置——最小面（W13 C1 删除收敛）。

历史（v1）：11 节子配置 + ConfigManager 全套加载器（YAML/JSON/ENV/reload/
save/update）+ configs/default.yaml 模板。W13 架构审查证实生产消费仅两处：
gui/main.setup_logging 读 .logging、predict 页设备解析（现改读 user_settings）；
其余 9 节（model/detection/data/prompts/security/monitoring/server/cache/
training）与全部加载器生产引用 = 0，default.yaml 永不加载。

现状：本模块只保留存活的静态默认值（logging + inference 两节 + BaseConfig
骨架 + get_config 单例）。用户可变配置（主题/语言/设备/精度/路径）统一走
configs/user_settings.json，单一访问器 gui/core/settings_io.py。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TilingConfig:
    """分块推理配置（对标 SKolpha 大图分块推理）。"""
    enable: bool = False
    tile_size: int = 512
    overlap: int = 64


@dataclass
class InferenceConfig:
    """推理配置（静态默认值；运行时设备以 user_settings.device 为准）。"""
    batch_size: int = 1
    num_workers: int = 4
    device: str = "cuda"
    precision: str = "fp16"
    enable_cache: bool = True
    enable_profiling: bool = False
    cache_size: int = 1000
    tensorrt_engine_path: str | None = None
    tiling: TilingConfig = field(default_factory=TilingConfig)


@dataclass
class LoggingConfig:
    """日志配置（gui/main.setup_logging 唯一消费方）。"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_dir: str = "./logs"
    enable_file_logging: bool = True
    enable_console_logging: bool = True
    max_file_size_mb: int = 10
    backup_count: int = 5


@dataclass
class BaseConfig:
    """基础配置骨架（logging + inference 两个存活节）。"""
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> bool:
        """验证存活节字段范围；非法值抛 ValueError。"""
        if self.inference.device not in ("cuda", "cpu", "mps"):
            raise ValueError(f"Invalid device: {self.inference.device}")

        if self.inference.precision not in ("fp32", "fp16", "bf16"):
            raise ValueError(f"Invalid precision: {self.inference.precision}")

        if self.inference.batch_size < 1:
            raise ValueError(f"Invalid batch_size: {self.inference.batch_size}")

        logger.info("Configuration validation passed")
        return True


# 全局配置单例（模块级懒初始化，进程内共享；测试可经 _config 重置）
_config: BaseConfig | None = None


def get_config() -> BaseConfig:
    """获取全局配置（懒初始化单例）。"""
    global _config
    if _config is None:
        _config = BaseConfig()
    return _config


__all__ = [
    "BaseConfig",
    "InferenceConfig",
    "LoggingConfig",
    "TilingConfig",
    "get_config",
]
