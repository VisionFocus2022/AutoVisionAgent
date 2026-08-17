"""core.config 最小面直测（W13 C1 删除收敛后重写）。

覆盖点：
- get_config() 懒初始化单例（原 ConfigManager 单例语义的存活面）
- logging / inference 两个存活节的默认值
- validate() 合法默认通过 / 非法 device、precision、batch_size 抛 ValueError

被删 API（ConfigManager 全套加载器与 update/save、load_config、Environment、
model/detection/data/prompts/security/monitoring/server/cache/training 9 个
零引用节）的用例随删——原 14 例（详见 W13 C1 报告 testsDeletedCount）。
"""
import pytest


@pytest.mark.unit
class TestGetConfigSingleton:
    """get_config 懒初始化单例（等价原 ConfigManager 单例可观测面）。"""

    def test_singleton_identity(self):
        import core.config as cfg_mod

        assert cfg_mod.get_config() is cfg_mod.get_config()

    def test_reset_yields_fresh_defaults(self, monkeypatch):
        """重置单例后得到全新默认实例（原 reinit 守卫测试语义）。"""
        import core.config as cfg_mod

        cfg = cfg_mod.get_config()
        old_device = cfg.inference.device
        cfg.inference.device = "cpu"

        monkeypatch.setattr(cfg_mod, "_config", None)
        fresh = cfg_mod.get_config()
        assert fresh is not cfg
        assert fresh.inference.device == "cuda"

        cfg.inference.device = old_device  # 恢复，避免污染其他用例


@pytest.mark.unit
class TestSurvivingSectionDefaults:
    """存活节（logging / inference）默认值完整性。"""

    def test_logging_defaults(self):
        from core.config import LoggingConfig

        lc = LoggingConfig()
        assert lc.level == "INFO"
        assert lc.log_dir == "./logs"
        assert lc.max_file_size_mb == 10
        assert lc.backup_count == 5
        assert "%(levelname)s" in lc.format

    def test_inference_defaults(self):
        from core.config import InferenceConfig

        inf = InferenceConfig()
        assert inf.device == "cuda"
        assert inf.precision == "fp16"
        assert inf.batch_size == 1
        assert inf.num_workers == 4
        assert inf.enable_cache is True

    def test_inference_has_tiling(self):
        from core.config import InferenceConfig

        inf = InferenceConfig()
        assert inf.tiling.enable is False
        assert inf.tiling.tile_size == 512
        assert inf.tiling.overlap == 64

    def test_base_config_sections(self):
        from core.config import BaseConfig

        cfg = BaseConfig()
        assert hasattr(cfg.logging, "level")
        assert hasattr(cfg.inference, "device")


@pytest.mark.unit
class TestValidate:
    """validate() 存活节校验分支。"""

    def test_defaults_pass(self):
        from core.config import BaseConfig

        assert BaseConfig().validate() is True

    def test_bad_device_raises(self):
        from core.config import BaseConfig

        cfg = BaseConfig()
        cfg.inference.device = "tpu"
        with pytest.raises(ValueError, match="device"):
            cfg.validate()

    def test_bad_precision_raises(self):
        from core.config import BaseConfig

        cfg = BaseConfig()
        cfg.inference.precision = "int4"
        with pytest.raises(ValueError, match="precision"):
            cfg.validate()

    def test_bad_batch_size_raises(self):
        from core.config import BaseConfig

        cfg = BaseConfig()
        cfg.inference.batch_size = 0
        with pytest.raises(ValueError, match="batch_size"):
            cfg.validate()


@pytest.mark.unit
def test_deleted_api_stays_deleted():
    """W13 C1 删除面防复活：ConfigManager / load_config / Environment /
    9 个零引用节不得回归（它们在生产零引用，回读 user_settings.json）。"""
    import core.config as cfg_mod

    for name in (
        "ConfigManager", "config_manager", "load_config", "Environment",
        "ModelConfig", "DetectionConfig", "DataConfig", "PromptConfig",
        "SecurityConfig", "MonitoringConfig", "ServerConfig", "CacheConfig",
        "TrainingConfig",
    ):
        assert not hasattr(cfg_mod, name), f"已删 API 复活: {name}"
