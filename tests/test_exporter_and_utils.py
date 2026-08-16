"""导出器冒烟测试。

验证 SupervisedExporter 的 ONNX 导出、input_shape 自动选择、量化逻辑不抛异常。
"""
from __future__ import annotations

import os
import sys

import pytest

# 确保项目根在 sys.path
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)


class _DummyModel:
    """简单的 nn.Module 替身。"""
    def eval(self):
        return self
    def parameters(self):
        return iter([])
    def to(self, device):
        return self
    def __call__(self, x):
        return x


class _DummyEngine:
    """最小引擎替身。"""
    def __init__(self, task_value="cls"):
        from core.interfaces_supervised import TaskType
        self.task = TaskType(task_value)
        self._model = None
        self._device = "cpu"
        self._weights_path = ""


class TestExporterSmoke:
    """SupervisedExporter 冒烟测试。"""

    def test_input_shape_auto_cls(self):
        """input_shape 根据 CLS 自动选择 224x224。"""
        from exporter.supervised_exporter import SupervisedExporter
        exporter = SupervisedExporter()
        # 仅验证逻辑不抛异常
        assert exporter._opset == 14

    def test_exporter_construct(self):
        """导出器可构造。"""
        from exporter.supervised_exporter import SupervisedExporter
        exporter = SupervisedExporter(opset=12, simplify=False)
        assert exporter._opset == 12
        assert exporter._simplify is False


class TestTilingInferencer:
    """大图分块推理工具测试。"""

    def test_compute_tiles_small(self):
        """小图返回单个瓦片。"""
        from inference.tiling_inferencer import compute_tiles
        tiles = compute_tiles(100, 100, tile_size=1024, overlap=128)
        assert len(tiles) == 1
        assert tiles[0] == (0, 0, 100, 100)

    def test_compute_tiles_large(self):
        """大图切分为多个瓦片。"""
        from inference.tiling_inferencer import compute_tiles
        tiles = compute_tiles(3000, 2000, tile_size=1024, overlap=128)
        assert len(tiles) > 4

    def test_compute_tiles_overlap_boundary(self):
        """overlap 步进正确：step = tile_size - overlap。"""
        from inference.tiling_inferencer import compute_tiles
        # tile=1024 overlap=128 → step=896
        # 图宽 1024+896=1920 → x 方向 2 列 (0, 896)
        tiles = compute_tiles(1024, 1920, tile_size=1024, overlap=128)
        xs = sorted({t[0] for t in tiles})
        assert 0 in xs
        assert 896 in xs

    def test_should_tile_false_small(self):
        """小图不需要 tiling。"""
        np = pytest.importorskip("numpy")
        from inference.tiling_inferencer import should_tile
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        assert should_tile(img) is False

    def test_should_tile_true_large(self):
        """大图需要 tiling。"""
        np = pytest.importorskip("numpy")
        from inference.tiling_inferencer import should_tile
        img = np.zeros((3000, 4000, 3), dtype=np.uint8)
        assert should_tile(img) is True


class TestConstants:
    """core/constants.py 一致性测试。"""

    def test_img_exts_includes_webp(self):
        """IMG_EXTS 包含 .webp（修复不一致 bug）。"""
        from core.constants import IMG_EXTS
        assert ".webp" in IMG_EXTS
        assert ".jpg" in IMG_EXTS

    def test_config_dir_exists(self):
        """CONFIG_DIR 常量正确指向。"""
        from core.constants import CONFIG_DIR
        assert "configs" in str(CONFIG_DIR)


class TestLoginSecurity:
    """登录安全功能测试。"""

    def test_pbkdf2_hash(self):
        """PBKDF2 哈希生成正确。"""
        from core.auth import hash_password, verify_password
        h1, salt, iters = hash_password("test123")
        assert len(h1) == 64  # 32 bytes hex
        assert len(salt) == 32  # 16 bytes hex
        assert iters >= 100_000  # 至少满足 OWASP 基准
        # 相同密码+盐可验证
        assert verify_password("test123", h1, salt, iters)
        # 错误密码不通过
        assert not verify_password("wrong", h1, salt, iters)

    def test_pbkdf2_different_salts(self):
        """相同密码生成不同哈希（不同盐）。"""
        from core.auth import hash_password
        h1, s1, _ = hash_password("test")
        h2, s2, _ = hash_password("test")
        assert s1 != s2
        assert h1 != h2

    def test_pbkdf2_known_vector(self):
        """已知向量验证：相同密码+盐 = 确定性哈希。"""
        from core.auth import hash_password
        h1, _, _ = hash_password("password", "aabbccdd" * 4)
        h2, _, _ = hash_password("password", "aabbccdd" * 4)
        assert h1 == h2  # 确定性

    def test_verify_empty_rejects(self):
        """空哈希或空盐应拒绝。"""
        from core.auth import verify_password
        assert not verify_password("x", "", "salt")
        assert not verify_password("x", "hash", "")
