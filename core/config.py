"""
统一配置管理系统
提供集中式配置管理、环境变量支持、配置验证等功能
"""
import os
import yaml
import json
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, get_type_hints
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T', bound='BaseConfig')


class Environment(Enum):
    """环境类型"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class ModelConfig:
    """模型配置"""
    # DINOv3配置
    dinov3_name: str = "dinov2_vits14"
    dinov3_pretrained: bool = True
    dinov3_freeze: bool = True
    dinov3_output_layers: list = field(default_factory=lambda: [6, 12, 18, 24])
    dinov3_embed_dim: int = 384
    dinov3_patch_size: int = 14

    # CLIP配置
    clip_name: str = "ViT-B/32"
    clip_pretrained: bool = True
    clip_freeze: bool = True
    clip_embed_dim: int = 512

    # 适配器配置
    adapter_hidden_dim_ratio: float = 0.25
    adapter_use_ln: bool = True
    adapter_dropout: float = 0.1

    # 融合配置
    fusion_method: str = "weighted_average"
    fusion_learnable_weights: bool = True


@dataclass
class TilingConfig:
    """分块推理配置（对标 SKolpha 大图分块推理）。"""
    enable: bool = False
    tile_size: int = 512
    overlap: int = 64


@dataclass
class InferenceConfig:
    """推理配置"""
    batch_size: int = 1
    num_workers: int = 4
    device: str = "cuda"
    precision: str = "fp16"
    enable_cache: bool = True
    enable_profiling: bool = False
    cache_size: int = 1000
    tensorrt_engine_path: Optional[str] = None
    tiling: TilingConfig = field(default_factory=TilingConfig)


@dataclass
class DetectionConfig:
    """检测配置"""
    anomaly_threshold: float = 0.5
    min_area: int = 100
    score_type: str = "cosine_similarity"
    use_multi_scale: bool = False
    scales: list = field(default_factory=lambda: [224, 336, 518])


@dataclass
class DataConfig:
    """数据配置"""
    image_size: int = 518
    mean: list = field(default_factory=lambda: [0.485, 0.456, 0.406])
    std: list = field(default_factory=lambda: [0.229, 0.224, 0.225])
    augment: bool = False


@dataclass
class PromptConfig:
    """提示配置"""
    normal_templates: list = field(default_factory=lambda: [
        "a photo of a normal {object}",
        "a photo of a good {object}",
        "a photo of a flawless {object}",
    ])
    abnormal_templates: list = field(default_factory=lambda: [
        "a photo of a defective {object}",
        "a photo of a damaged {object}",
        "a photo of an anomalous {object}",
    ])


@dataclass
class SecurityConfig:
    """安全配置"""
    max_image_size: int = 10 * 1024 * 1024  # 10MB
    max_image_dimension: int = 4096
    min_image_dimension: int = 64
    max_text_length: int = 1000
    enable_rate_limiting: bool = True
    rate_limit_per_minute: int = 60


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_dir: str = "./logs"
    enable_file_logging: bool = True
    enable_console_logging: bool = True
    max_file_size_mb: int = 10
    backup_count: int = 5


@dataclass
class MonitoringConfig:
    """监控配置"""
    enable_metrics: bool = True
    enable_tracing: bool = False
    metrics_port: int = 9090
    tracing_endpoint: Optional[str] = None
    performance_sampling_rate: float = 0.1


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 7860
    workers: int = 1
    timeout: int = 120
    max_request_size: int = 10 * 1024 * 1024


@dataclass
class TrainingConfig:
    """训练配置（对标 configs/default.yaml training 节）。"""
    default_epochs: int = 100
    default_lr: float = 0.001
    default_batch_size: int = 8
    checkpoint_interval: int = 5
    max_checkpoints: int = 3


@dataclass
class CacheConfig:
    """缓存配置"""
    backend: str = "memory"  # memory, redis, memcached
    ttl: int = 3600  # 秒
    max_size: int = 10000
    redis_host: Optional[str] = None
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None


@dataclass
class BaseConfig:
    """基础配置类"""
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    model: ModelConfig = field(default_factory=ModelConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    data: DataConfig = field(default_factory=DataConfig)
    prompts: PromptConfig = field(default_factory=PromptConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)

    def validate(self) -> bool:
        """验证配置"""
        try:
            # 验证推理配置
            if self.inference.device not in ["cuda", "cpu", "mps"]:
                raise ValueError(f"Invalid device: {self.inference.device}")

            if self.inference.precision not in ["fp32", "fp16", "bf16"]:
                raise ValueError(f"Invalid precision: {self.inference.precision}")

            # 验证阈值范围
            if not 0.0 <= self.detection.anomaly_threshold <= 1.0:
                raise ValueError(f"Invalid threshold: {self.detection.anomaly_threshold}")

            # 验证图像大小
            if self.data.image_size < 64 or self.data.image_size > 4096:
                raise ValueError(f"Invalid image_size: {self.data.image_size}")

            # R5-9: 验证训练参数范围
            if self.training.default_epochs < 1:
                raise ValueError(
                    f"Invalid default_epochs: {self.training.default_epochs}"
                )
            if self.training.default_lr <= 0 or self.training.default_lr > 1.0:
                raise ValueError(
                    f"Invalid default_lr: {self.training.default_lr}"
                )
            if self.training.default_batch_size < 1:
                raise ValueError(
                    f"Invalid default_batch_size: {self.training.default_batch_size}"
                )
            if self.training.checkpoint_interval < 1:
                raise ValueError(
                    f"Invalid checkpoint_interval: {self.training.checkpoint_interval}"
                )

            logger.info("Configuration validation passed")
            return True

        except (ValueError, TypeError, AttributeError) as e:
            logger.error(f"Configuration validation failed: {e}")
            raise

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（枚举自动转为 .value 字符串，确保可序列化）"""
        raw = asdict(self)
        # 递归把 Environment 枚举转成 .value，保证 YAML/JSON 安全序列化
        if isinstance(raw.get("environment"), Environment):
            raw["environment"] = raw["environment"].value
        return raw

    def to_yaml(self, path: Optional[Path] = None) -> str:
        """转换为YAML"""
        yaml_str = yaml.dump(self.to_dict(), default_flow_style=False, allow_unicode=True)
        if path:
            path.write_text(yaml_str)
        return yaml_str

    def to_json(self, path: Optional[Path] = None) -> str:
        """转换为JSON"""
        json_str = json.dumps(self.to_dict(), indent=2, default=str)
        if path:
            path.write_text(json_str)
        return json_str


class ConfigManager:
    """
    配置管理器

    提供配置加载、验证、更新等功能。
    支持多种配置源：YAML文件、JSON文件、环境变量、命令行参数。
    """

    _instance: Optional['ConfigManager'] = None
    _config: Optional[BaseConfig] = None

    def __new__(cls) -> 'ConfigManager':
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化配置管理器"""
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        if self._config is None:
            self._config = BaseConfig()

    @classmethod
    def load_from_yaml(cls: Type[T], path: str | Path) -> T:
        """从YAML文件加载配置（带回退链）。

        回退顺序：
        1. 指定路径 (path)
        2. configs/default.yaml (模板)
        3. BaseConfig 默认值
        """
        path = Path(path)
        if not path.exists():
            # 回退到模板
            import os
            template = Path(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "configs", "default.yaml"
            ))
            if template.exists():
                logger.warning(f"配置文件 {path} 不存在，回退到模板 {template}")
                path = template
            else:
                logger.warning(f"配置文件 {path} 不存在且无模板，使用默认配置")
                manager = cls()
                return manager

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        manager = cls()
        manager._config = BaseConfig()  # 重置为默认值，避免上一个配置的残留
        manager._apply_dict(data)
        manager._config.validate()

        logger.info(f"Loaded configuration from {path}")
        return manager

    @classmethod
    def load_from_json(cls: Type[T], path: str | Path) -> T:
        """从JSON文件加载配置"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        manager = cls()
        manager._config = BaseConfig()  # 重置为默认值
        manager._apply_dict(data)
        manager._config.validate()

        logger.info(f"Loaded configuration from {path}")
        return manager

    @classmethod
    def load_from_env(cls: Type[T], prefix: str = "APP_") -> T:
        """从环境变量加载配置"""
        manager = cls()

        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower()
                manager._set_nested_value(config_key, value)

        manager._config.validate()
        logger.info("Loaded configuration from environment variables")
        return manager

    def _apply_dict(self, data: Dict[str, Any], parent_key: str = "") -> None:
        """递归应用字典配置。

        自文档化支持：以 ``?`` 开头的键被视为内联注释（对标 SKolpha ?字段模式），
        自动跳过。例如::

            anomaly_threshold: 0.5
            ?anomaly_threshold: "异常分数阈值"
        """
        for key, value in data.items():
            # 跳过自文档化字段（? 前缀）
            if isinstance(key, str) and key.startswith("?"):
                continue

            full_key = f"{parent_key}.{key}" if parent_key else key

            if isinstance(value, dict):
                self._apply_dict(value, full_key)
            else:
                self._set_nested_value(full_key, value)

    def _set_nested_value(self, key: str, value: Any) -> None:
        """
        设置嵌套配置值

        Args:
            key: 配置键，支持点分隔的嵌套键
            value: 配置值

        Raises:
            ValueError: 键不存在或类型转换失败
        """
        keys = key.split('.')
        config = self._config

        try:
            # 导航到父对象
            config = self._navigate_to_parent(config, keys[:-1])

            # 设置值
            final_key = keys[-1]
            if not hasattr(config, final_key):
                raise ValueError(f"Unknown config key: {final_key}")

            # 类型转换并设置
            converted_value = self._convert_value_type(config, final_key, value)
            setattr(config, final_key, converted_value)

        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to set config '{key}': {e}")
            raise

    def _navigate_to_parent(self, config: Any, keys: list) -> Any:
        """
        导航到父配置对象

        Args:
            config: 起始配置对象
            keys: 键列表（不包含最终键）

        Returns:
            父配置对象

        Raises:
            AttributeError: 导航路径不存在
        """
        for k in keys:
            if hasattr(config, k):
                config = getattr(config, k)
            else:
                raise AttributeError(f"Unknown config key: {k}")
        return config

    def _convert_value_type(self, config: Any, key: str, value: Any) -> Any:
        """
        根据当前值类型转换输入值

        Args:
            config: 配置对象
            key: 配置键
            value: 输入值

        Returns:
            转换后的值

        Raises:
            ValueError: 类型转换失败
        """
        current_value = getattr(config, key)

        try:
            # Environment 枚举：接受字符串值或枚举实例
            if isinstance(current_value, Environment):
                if isinstance(value, Environment):
                    return value
                return Environment(value)
            if isinstance(current_value, bool):
                return self._to_bool(value)
            elif isinstance(current_value, int):
                return int(value)
            elif isinstance(current_value, float):
                return float(value)
            elif isinstance(current_value, list):
                return self._to_list(value)
            elif isinstance(current_value, str):
                return str(value)
            else:
                return value

        except (ValueError, TypeError) as e:
            raise ValueError(f"Type conversion failed for '{key}': {e}") from e

    def _to_bool(self, value: Any) -> bool:
        """转换为布尔值"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)

    def _to_list(self, value: Any) -> list:
        """转换为列表"""
        if isinstance(value, list):
            return value
        if isinstance(value, (tuple, set)):
            return list(value)
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return [value]

    def get(self) -> BaseConfig:
        """获取配置"""
        return self._config

    def update(self, **kwargs) -> None:
        """更新配置

        支持点分隔嵌套键，如 ``inference_device`` 等价于
        ``inference.device``。两种写法均可用。
        """
        for key, value in kwargs.items():
            # 支持 inference_device 风格（下划线作为分隔符）
            if "_" in key and "." not in key:
                parts = key.split("_")
                # 尝试两级路径：第一段是子配置名
                if len(parts) >= 2 and hasattr(self._config, parts[0]):
                    dotted = parts[0] + "." + "_".join(parts[1:])
                    try:
                        self._set_nested_value(dotted, value)
                        continue
                    except (ValueError, AttributeError):
                        pass  # 回退到直接尝试
            self._set_nested_value(key, value)
        self._config.validate()

    def reload(self, path: str | Path) -> None:
        """重新加载配置"""
        path = Path(path)
        if path.suffix in ['.yml', '.yaml']:
            self.load_from_yaml(path)
        elif path.suffix == '.json':
            self.load_from_json(path)

    def save(self, path: str | Path, format: str = 'yaml') -> None:
        """保存配置"""
        path = Path(path)
        if format == 'yaml':
            self._config.to_yaml(path)
        elif format == 'json':
            self._config.to_json(path)
        else:
            raise ValueError(f"Unsupported format: {format}")

        logger.info(f"Saved configuration to {path}")


# 全局配置实例
config_manager = ConfigManager()


def get_config() -> BaseConfig:
    """获取全局配置"""
    return config_manager.get()


def load_config(path: str | Path) -> BaseConfig:
    """加载配置文件"""
    path = Path(path)
    if path.suffix in ['.yml', '.yaml']:
        return config_manager.load_from_yaml(path)
    elif path.suffix == '.json':
        return config_manager.load_from_json(path)
    else:
        raise ValueError(f"Unsupported config format: {path.suffix}")
