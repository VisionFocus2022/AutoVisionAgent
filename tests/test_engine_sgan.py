"""sgan blend 引擎功能测试（T-FIX-1-06）。

真 load→infer 测试：copy-paste blend 不需要模型权重，
仅需缺陷库目录 → 可完整验证真合成 + mask 产出。
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestSganBlendFunctional:
    """SganBlendEngine 真 blend 功能测试。"""

    def test_blend_real_infer(self, tmp_path):
        """真 load→infer：OK 模板 + 缺陷库 → 合成图 + mask。"""
        import cv2

        from models.supervised.engines.sgan_blend import SganBlendEngine
        from core.interfaces_supervised import TaskType

        # 准备缺陷库
        flaw_dir = tmp_path / "flaws"
        flaw_dir.mkdir()
        for i in range(3):
            img = np.random.RandomState(i).randint(0, 256, (20, 20, 3), dtype=np.uint8)
            cv2.imwrite(str(flaw_dir / f"flaw_{i}.png"), img)

        engine = SganBlendEngine()
        engine.load(flaw_database=str(flaw_dir), device="cpu")

        # OK 模板
        template = np.ones((100, 100, 3), dtype=np.uint8) * 200

        result = engine.infer(template)

        # 验证结果结构
        assert result.task == TaskType.SGAN
        assert result.score is not None
        assert result.score > 0  # 有缺陷占比

        # 验证 extra 含合成图和 mask
        extra_dict = dict(result.extra)
        assert "synthesized_image" in extra_dict
        assert "defect_mask" in extra_dict

        synth = extra_dict["synthesized_image"]
        mask = extra_dict["defect_mask"]

        # 合成图与模板尺寸一致
        assert synth.shape[:2] == template.shape[:2]
        # mask 是二值的
        assert set(np.unique(mask)).issubset({0, 1})

    def test_blend_not_copy(self, tmp_path):
        """合成图 ≠ 输入拷贝（score 非 0，mask 有缺陷区域）。"""
        import cv2

        from models.supervised.engines.sgan_blend import SganBlendEngine

        flaw_dir = tmp_path / "flaws"
        flaw_dir.mkdir()
        # 用有明显纹理的缺陷图（非纯色）
        flaw_img = np.random.RandomState(42).randint(0, 128, (15, 15, 3), dtype=np.uint8)
        cv2.imwrite(str(flaw_dir / "flaw.png"), flaw_img)

        engine = SganBlendEngine()
        engine.load(flaw_database=str(flaw_dir), device="cpu")

        template = np.ones((80, 80, 3), dtype=np.uint8) * 255
        result = engine.infer(template)

        extra_dict = dict(result.extra)
        mask = extra_dict["defect_mask"]

        # mask 有非零区域（缺陷被合成了）
        assert mask.sum() > 0
        # score > 0 说明有缺陷区域
        assert result.score > 0

    def test_no_flaw_database_raises(self):
        """无缺陷库 → raise（诚实回退，不返假数据）。"""
        from models.supervised.engines.sgan_blend import SganBlendEngine
        from core.exceptions import SupervisedEngineError

        engine = SganBlendEngine()
        # load 空路径 → _flaw_files 为空 → infer raise
        engine.load(device="cpu")

        with pytest.raises(SupervisedEngineError):
            engine.infer(np.zeros((64, 64, 3), dtype=np.uint8))
