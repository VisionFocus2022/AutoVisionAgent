"""M2 新增引擎契约测试（T-AVA-08 验证）。

覆盖 6 个 M2 引擎：cls / pose / pseg / sseg / sgan / super。

验证每个引擎的错误路径和元数据（不依赖真实模型权重）：
- 未加载时 infer() 抛 SupervisedEngineError
- load() 不存在路径抛 SupervisedEngineError
- .task 属性正确
- info() 返回包含必需键的字典
"""
from __future__ import annotations

import pytest

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import TaskType
from models.supervised.engines.cls_torchvision import ClsTorchvisionEngine
from models.supervised.engines.pose_yolo import PoseYoloEngine
from models.supervised.engines.pseg_yolo import PsegYoloEngine
from models.supervised.engines.sgan_blend import SganBlendEngine
from models.supervised.engines.sseg_mmseg import SsegMmsegEngine
from models.supervised.engines.super_cv2 import SuperCv2Engine

_DUMMY_IMG = "dummy_input_placeholder"

# (engine_class, expected_task)
_M2_ENGINES = [
    (ClsTorchvisionEngine, TaskType.CLS),
    (PoseYoloEngine, TaskType.POSE),
    (PsegYoloEngine, TaskType.PSEG),
    (SsegMmsegEngine, TaskType.SSEG),
    (SganBlendEngine, TaskType.SGAN),
    (SuperCv2Engine, TaskType.SUPER),
]


@pytest.mark.unit
@pytest.mark.parametrize("engine_cls,expected_task", _M2_ENGINES)
class TestM2EngineContracts:
    """参数化契约测试：每引擎验证相同的行为集。"""

    def test_task_attribute(self, engine_cls, expected_task):
        """引擎的 .task 属性匹配预期 TaskType。"""
        eng = engine_cls()
        assert eng.task == expected_task

    def test_infer_not_loaded_raises(self, engine_cls, expected_task):
        """未加载权重时 infer() 抛 SupervisedEngineError。"""
        eng = engine_cls()
        with pytest.raises(SupervisedEngineError) as exc_info:
            eng.infer(_DUMMY_IMG)
        assert exc_info.value.details.get("task") == expected_task.value

    def test_load_missing_raises(self, engine_cls, expected_task, tmp_path):
        """加载不存在路径抛 SupervisedEngineError。"""
        eng = engine_cls()
        fake_path = str(tmp_path / "nonexistent_weights.pth")
        with pytest.raises(SupervisedEngineError) as exc_info:
            eng.load(fake_path)
        assert exc_info.value.details.get("task") == expected_task.value

    def test_info_structure(self, engine_cls, expected_task):
        """info() 返回字典，包含必需键且 loaded=False。"""
        eng = engine_cls()
        info = eng.info()
        assert isinstance(info, dict)
        assert info["type"] == expected_task.value
        assert info["name"] == engine_cls.__name__
        assert info["loaded"] is False
        assert info["file"] is None
        assert info["path"] is None

    def test_release_resets_model(self, engine_cls, expected_task):
        """release() 后 info loaded=False。"""
        eng = engine_cls()
        eng.release()
        assert eng.info()["loaded"] is False


# ---- sgan 额外方法 ---- #
class TestSganFlawDatabase:
    """SganBlendEngine 特有的缺陷库设置（W2 翻转：路径不存在诚实 raise）。"""

    def test_set_flaw_database_real_dir(self, tmp_path):
        eng = SganBlendEngine()
        eng.set_flaw_database(str(tmp_path))
        assert eng._flaw_database == str(tmp_path)

    def test_set_flaw_database_missing_raises(self):
        """W2 行为翻转：不存在的缺陷库路径不再静默存储，而是 raise。"""
        eng = SganBlendEngine()
        with pytest.raises(SupervisedEngineError):
            eng.set_flaw_database("/path/to/does_not_exist")

    def test_flaw_database_default_none(self):
        eng = SganBlendEngine()
        assert eng._flaw_database is None
