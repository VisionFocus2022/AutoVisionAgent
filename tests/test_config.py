"""ConfigManager 单元测试（R3-13 补齐核心模块测试覆盖）。

覆盖点：
- 单例重入守卫（_initialized）
- 默认值完整性
- YAML 加载 + 回退链
- 点分隔嵌套 update
- TilingConfig / TrainingConfig 新字段映射
"""
import pytest
import os
import tempfile


@pytest.mark.unit
class TestConfigManagerSingleton:
    """ConfigManager 单例行为。"""

    def test_singleton_identity(self):
        from core.config import ConfigManager
        a = ConfigManager()
        b = ConfigManager()
        assert a is b

    def test_reinit_guard(self):
        """多次 __init__ 不会重置已有配置。"""
        from core.config import ConfigManager
        mgr = ConfigManager()
        original_device = mgr.get().inference.device
        mgr.get().inference.device = "cpu"
        # 再次实例化不应该重置
        mgr2 = ConfigManager()
        assert mgr2.get().inference.device == "cpu"
        # 恢复
        mgr2.get().inference.device = original_device


@pytest.mark.unit
class TestDefaultConfig:
    """默认配置值完整性。"""

    def test_base_config_has_all_sections(self):
        from core.config import BaseConfig
        cfg = BaseConfig()
        for attr in (
            "model", "inference", "detection", "data", "prompts",
            "security", "logging", "monitoring", "server", "cache",
            "training",
        ):
            assert hasattr(cfg, attr), f"BaseConfig 缺少字段: {attr}"

    def test_inference_has_tiling(self):
        from core.config import InferenceConfig
        inf = InferenceConfig()
        assert hasattr(inf, "tiling")
        assert inf.tiling.enable is False
        assert inf.tiling.tile_size == 512
        assert inf.tiling.overlap == 64

    def test_training_config_defaults(self):
        from core.config import TrainingConfig
        tc = TrainingConfig()
        assert tc.default_epochs == 100
        assert tc.default_lr == 0.001
        assert tc.default_batch_size == 8
        assert tc.checkpoint_interval == 5
        assert tc.max_checkpoints == 3

    def test_to_dict_serializable(self):
        """to_dict 输出应可 JSON 序列化（Environment 枚举转 .value）。"""
        import json
        from core.config import BaseConfig
        cfg = BaseConfig()
        d = cfg.to_dict()
        assert isinstance(d["environment"], str)
        json.dumps(d)  # 不应抛异常


@pytest.mark.unit
class TestConfigManagerUpdate:
    """ConfigManager.update() 嵌套键设置。"""

    def test_update_dotted_key(self):
        from core.config import ConfigManager
        mgr = ConfigManager()
        mgr.update(**{"inference.device": "cpu"})
        assert mgr.get().inference.device == "cpu"

    def test_update_underscore_key(self):
        from core.config import ConfigManager
        mgr = ConfigManager()
        mgr.update(inference_device="cuda")
        assert mgr.get().inference.device == "cuda"

    def test_update_training_fields(self):
        from core.config import ConfigManager
        mgr = ConfigManager()
        mgr.update(**{"training.default_epochs": 50})
        assert mgr.get().training.default_epochs == 50

    def test_update_tiling_fields(self):
        from core.config import ConfigManager
        mgr = ConfigManager()
        mgr.update(**{"inference.tiling.tile_size": 1024})
        assert mgr.get().inference.tiling.tile_size == 1024


@pytest.mark.unit
class TestConfigManagerLoadYAML:
    """YAML 加载与回退链。"""

    def test_load_from_yaml_file(self, tmp_path):
        """从临时 YAML 文件加载配置。"""
        from core.config import ConfigManager
        yaml_content = """
inference:
  device: "cpu"
  precision: "fp32"
  batch_size: 4
  tiling:
    enable: true
    tile_size: 256
    overlap: 32
"""
        yaml_path = tmp_path / "test_config.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        mgr = ConfigManager.load_from_yaml(str(yaml_path))
        assert mgr.get().inference.device == "cpu"
        assert mgr.get().inference.precision == "fp32"
        assert mgr.get().inference.batch_size == 4
        assert mgr.get().inference.tiling.enable is True
        assert mgr.get().inference.tiling.tile_size == 256
        assert mgr.get().inference.tiling.overlap == 32

    def test_load_training_section(self, tmp_path):
        """从 YAML 加载 training 节。"""
        from core.config import ConfigManager
        yaml_content = """
training:
  default_epochs: 200
  default_lr: 0.0005
  default_batch_size: 16
"""
        yaml_path = tmp_path / "train_config.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        mgr = ConfigManager.load_from_yaml(str(yaml_path))
        assert mgr.get().training.default_epochs == 200
        assert mgr.get().training.default_lr == 0.0005
        assert mgr.get().training.default_batch_size == 16

    def test_self_documenting_keys_skipped(self, tmp_path):
        """? 前缀的自文档化键应被跳过。"""
        from core.config import ConfigManager
        yaml_content = """
inference:
  device: "cpu"
  "?device": "推理设备，可选 cuda/cpu/mps"
"""
        yaml_path = tmp_path / "doc_config.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        mgr = ConfigManager.load_from_yaml(str(yaml_path))
        assert mgr.get().inference.device == "cpu"


@pytest.mark.unit
class TestConfigManagerSaveLoad:
    """保存 → 加载往返一致性。"""

    def test_save_and_load_yaml(self, tmp_path):
        from core.config import ConfigManager
        mgr = ConfigManager()
        mgr.get().inference.device = "cpu"
        mgr.get().inference.batch_size = 8

        yaml_path = tmp_path / "saved.yaml"
        mgr.save(str(yaml_path), format="yaml")
        assert yaml_path.exists()

        mgr2 = ConfigManager.load_from_yaml(str(yaml_path))
        assert mgr2.get().inference.device == "cpu"
        assert mgr2.get().inference.batch_size == 8
