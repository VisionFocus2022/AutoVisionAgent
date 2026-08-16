"""
缺陷生成引擎（mmedit GAN）— FR-A8 / FR-G1

从 OK 模板图像合成缺陷数据（GAN-based defect generation）。
对标 SKolpha 的 sgan 任务，解决缺陷样本稀少问题。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine


@register_engine(TaskType.SGAN)
class SganMmeditEngine(AbstractTaskEngine):
    """mmedit 缺陷生成引擎。

    工作流：
    1. 输入 OK 模板图像 + 缺陷库参考
    2. GAN 合成缺陷图
    3. 输出到 DetectionResult.extra
    """

    def __init__(self) -> None:
        super().__init__(TaskType.SGAN)
        self._flaw_database: Optional[str] = None

    def load(
        self,
        weights_path: str,
        device: str = "cuda",
        flaw_database: str = "",
    ) -> None:
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        try:
            from mmedit.apis import init_model

            config_path = weights_path.replace(".pth", ".py")
            self._model = init_model(
                config_path, weights_path, device=device
            )
        except ImportError:
            # mmedit 未安装时回退
            self._model = self._safe_torch_load(weights_path, map_location="cpu")
        except Exception as exc:
            raise SupervisedEngineError(
                f"加载缺陷生成模型失败: {exc}", task=self.task.value
            ) from exc

        self._weights_path = weights_path
        self._device = device
        self._flaw_database = flaw_database

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: Optional[list] = None,
    ) -> DetectionResult:
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)

        import numpy as np

        arr = self._to_numpy(image)
        try:
            from mmedit.apis import generation_inference

            output = generation_inference(self._model, arr)
            # generation_inference 返回合成图
            if isinstance(output, dict):
                synthesized = output.get("fake_img", list(output.values())[0])
            else:
                synthesized = output
            synth_np = (synthesized * 255).astype(np.uint8) if synthesized.max() <= 1.0 else synthesized.astype(np.uint8)
        except ImportError:
            # 回退：直接返回输入（无 GAN 可用时）
            synth_np = arr.copy()

        return DetectionResult(
            task=TaskType.SGAN,
            score=1.0,
            labels=("synthesized",),
        ).with_extra("synthesized_image", synth_np)

    def set_flaw_database(self, db_path: str) -> None:
        """设置缺陷库路径。"""
        self._flaw_database = db_path


__all__ = ["SganMmeditEngine"]
