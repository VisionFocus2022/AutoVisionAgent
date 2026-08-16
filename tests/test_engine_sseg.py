"""sseg smp 引擎功能测试（W3-T2，自兄弟树 test_engine_sseg.py 移植）。

smp 已装于本树 venv（segmentation_models_pytorch==0.5.0），可动态创建小模型
→ 真 load→infer 测试，杜绝 ImportError 桩回退。
"""
from __future__ import annotations

import os

import numpy as np
import pytest

smp = pytest.importorskip("segmentation_models_pytorch")
torch = pytest.importorskip("torch")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestSsegSmpFunctional:
    """SsegSmpEngine 真 load→infer 功能测试。"""

    def test_real_load_infer(self, tmp_path):
        """动态创建小 smp 模型 → save → load → infer → 语义图。"""
        import segmentation_models_pytorch as smp
        import torch

        from models.supervised.engines.sseg_smp import SsegSmpEngine
        from core.interfaces_supervised import TaskType

        # 创建小模型并保存
        model = smp.DeepLabV3Plus(
            encoder_name="resnet18",
            encoder_weights=None,
            in_channels=3,
            classes=2,
        )
        ckpt_path = str(tmp_path / "sseg_test.pth")
        torch.save(model.state_dict(), ckpt_path)

        # 真加载 + 推理
        engine = SsegSmpEngine()
        engine.load(ckpt_path, device="cpu")

        img = np.random.RandomState(42).randint(0, 256, (64, 64, 3), dtype=np.uint8)
        result = engine.infer(img)

        # 验证结果结构
        assert result.task == TaskType.SSEG
        assert result.masks is not None
        # 语义图尺寸与输入一致
        pred = result.masks
        if hasattr(pred, "shape"):
            assert pred.shape == (64, 64)
        # 值在 [0, num_classes-1] 范围内
        pred_np = pred.numpy() if hasattr(pred, "numpy") else np.asarray(pred)
        assert pred_np.min() >= 0
        assert pred_np.max() < 2  # 2 classes

    def test_arch_from_checkpoint(self, tmp_path):
        """checkpoint 含 arch 元信息时正确构造模型。"""
        import segmentation_models_pytorch as smp
        import torch

        from models.supervised.engines.sseg_smp import SsegSmpEngine

        model = smp.FPN(
            encoder_name="resnet18",
            encoder_weights=None,
            in_channels=3,
            classes=3,
        )
        ckpt = {
            "arch": "FPN",
            "encoder_name": "resnet18",
            "num_classes": 3,
            "state_dict": model.state_dict(),
        }
        ckpt_path = str(tmp_path / "sseg_fpn.pth")
        torch.save(ckpt, ckpt_path)

        engine = SsegSmpEngine()
        engine.load(ckpt_path, device="cpu")
        assert engine._arch == "FPN"
        assert engine._num_classes == 3

    def test_missing_smp_raises_honestly(self, tmp_path, monkeypatch):
        """缺 smp 库时诚实 raise SupervisedEngineError（无测试桩回退）。"""
        import builtins

        from core.exceptions import SupervisedEngineError
        from models.supervised.engines.sseg_smp import SsegSmpEngine

        real_import = builtins.__import__

        def _no_smp(name, *args, **kwargs):
            if name == "segmentation_models_pytorch":
                raise ImportError("No module named 'segmentation_models_pytorch'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_smp)
        ckpt = tmp_path / "w.pth"
        ckpt.write_bytes(b"x")
        eng = SsegSmpEngine()
        with pytest.raises(SupervisedEngineError, match="segmentation_models_pytorch"):
            eng.load(str(ckpt), device="cpu")
