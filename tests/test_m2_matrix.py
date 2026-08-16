"""M2 任务矩阵集成测试（T-AVA-15 验证）。

验证 9 任务 × {注册, 构造, TaskType} 矩阵 + 双范式分发：
- 全 9 引擎通过 register_all_engines() 注册到默认注册表
- 每引擎可被 get_engine(TaskType.X) 解析
- VisionModelDispatcher 双范式路由正确
- generative_metrics (FID/LPIPS) 可计算（含回退路径）
"""
from __future__ import annotations

import numpy as np
import pytest

from core.interfaces_supervised import TaskType
from models.supervised import get_default_registry, get_engine
from models.supervised.engines import register_all_engines

# 全部 9 种 TaskType
_ALL_9_TASKS = list(TaskType)

# 预期引擎类名（register_all_engines 后；W2: sgan/super 真化换名）
_EXPECTED_ENGINE_NAMES = {
    TaskType.CLS: "ClsTorchvisionEngine",
    TaskType.DET: "DetYoloEngine",
    TaskType.SEG: "SegYoloEngine",
    TaskType.PSEG: "PsegYoloEngine",
    TaskType.POSE: "PoseYoloEngine",
    TaskType.SSEG: "SsegSmpEngine",
    TaskType.ABDET: "AbdetAnomalibEngine",
    TaskType.SGAN: "SganBlendEngine",
    TaskType.SUPER: "SuperCv2Engine",
}


@pytest.fixture(autouse=True)
def _ensure_all_registered():
    """每条测试前触发全量引擎注册。"""
    register_all_engines()


class TestRegistrationMatrix:
    """9 任务注册矩阵。"""

    @pytest.mark.e2e
    def test_all_9_tasks_registered(self):
        """register_all_engines() 后 9 种 TaskType 全部在注册表中。"""
        reg = get_default_registry()
        registered = set(reg.list())
        for task in _ALL_9_TASKS:
            assert task in registered, f"{task.value} 未注册"

    @pytest.mark.e2e
    @pytest.mark.parametrize("task", _ALL_9_TASKS, ids=lambda t: t.value)
    def test_engine_resolvable(self, task):
        """每引擎可被 get_engine(TaskType.X) 解析，且类名正确。"""
        reg = get_default_registry()
        reg.clear_cache(task)
        engine = get_engine(task)
        assert engine.__class__.__name__ == _EXPECTED_ENGINE_NAMES[task]

    @pytest.mark.e2e
    @pytest.mark.parametrize("task", _ALL_9_TASKS, ids=lambda t: t.value)
    def test_engine_task_attribute(self, task):
        """每引擎的 .task 属性等于其 TaskType。"""
        engine = get_engine(task)
        assert engine.task == task


class TestDispatcherMatrix:
    """VisionModelDispatcher 双范式分发。"""

    @pytest.mark.e2e
    def test_list_all_tasks_count(self):
        """list_all_tasks 返回 9 有监督 + 1 零样本 = 10。"""
        from industrial_vision_platform.vision_dispatcher import VisionModelDispatcher

        tasks = VisionModelDispatcher.list_all_tasks()
        assert len(tasks) == 10
        task_values = {t["task"] for t in tasks}
        assert "zero_shot" in task_values
        for task in _ALL_9_TASKS:
            assert task.value in task_values

    @pytest.mark.e2e
    def test_dispatcher_init(self):
        """VisionModelDispatcher 初始化为空。"""
        from industrial_vision_platform.vision_dispatcher import (
            VisionModelDispatcher,
        )

        dispatcher = VisionModelDispatcher()
        assert dispatcher.zero_shot_ready is False
        assert dispatcher.loaded_tasks == []

    @pytest.mark.e2e
    def test_dispatcher_zero_shot_not_loaded_raises(self):
        """未加载零样本检测器时 infer_zero_shot 抛 RuntimeError。"""
        from industrial_vision_platform.vision_dispatcher import (
            VisionModelDispatcher,
        )

        dispatcher = VisionModelDispatcher()
        with pytest.raises(RuntimeError, match="零样本检测器未加载"):
            dispatcher.infer_zero_shot(np.zeros((32, 32, 3), dtype=np.uint8))

    @pytest.mark.e2e
    def test_dispatcher_supervised_not_loaded_raises(self):
        """未加载有监督引擎时 infer_supervised 抛 RuntimeError。"""
        from industrial_vision_platform.vision_dispatcher import (
            VisionModelDispatcher,
        )

        dispatcher = VisionModelDispatcher()
        with pytest.raises(RuntimeError, match="引擎未加载"):
            dispatcher.infer_supervised(TaskType.DET, np.zeros((32, 32, 3), dtype=np.uint8))

    @pytest.mark.e2e
    def test_dispatcher_task_info(self):
        """get_task_info 返回正确的范式信息。"""
        from industrial_vision_platform.vision_dispatcher import (
            VisionModelDispatcher,
        )

        dispatcher = VisionModelDispatcher()
        info = dispatcher.get_task_info("det")
        assert info["paradigm"] == "supervised"
        assert info["requires_training"] is True
        assert info["loaded"] is False

        info_zs = dispatcher.get_task_info("zero_shot")
        assert info_zs["paradigm"] == "zero-shot"
        assert info_zs["requires_training"] is False

    @pytest.mark.e2e
    def test_dispatcher_auto_route_unloaded(self):
        """auto 模式但引擎未加载 → RuntimeError。"""
        from industrial_vision_platform.vision_dispatcher import (
            VisionModelDispatcher,
        )

        dispatcher = VisionModelDispatcher()
        with pytest.raises(RuntimeError):
            dispatcher.infer("det", np.zeros((32, 32, 3), dtype=np.uint8))


class TestGenerativeMetrics:
    """generative_metrics 模块测试（FID/LPIPS 回退路径）。"""

    @pytest.mark.e2e
    def test_perceptual_loss_fallback_l2(self):
        """lpips 未安装 → 回退到 L2 像素损失。"""
        from evaluation.generative_metrics import perceptual_loss

        img1 = np.zeros((32, 32, 3), dtype=np.uint8)
        img2 = np.ones((32, 32, 3), dtype=np.uint8)
        result = perceptual_loss([img1], [img2])
        assert isinstance(result, float)
        assert result > 0.0  # 不同图 → 正损失

    @pytest.mark.e2e
    def test_perceptual_loss_identical(self):
        """相同图 → L2 损失 = 0。"""
        from evaluation.generative_metrics import perceptual_loss

        img = np.random.RandomState(42).randint(0, 256, (32, 32, 3), dtype=np.uint8)
        result = perceptual_loss([img], [img])
        assert result == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.e2e
    def test_sqrtm_matrix_square(self):
        """_sqrtm 矩阵开方（对称正定矩阵回乘近似恒等）。"""
        from evaluation.generative_metrics import _sqrtm

        mat = np.array([[4.0, 0.0], [0.0, 9.0]])
        sqrt_mat, ok = _sqrtm(mat)
        assert ok is True
        assert sqrt_mat[0, 0] == pytest.approx(2.0, abs=0.01)
        assert sqrt_mat[1, 1] == pytest.approx(3.0, abs=0.01)
