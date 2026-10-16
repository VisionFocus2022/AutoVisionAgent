"""Real-ESRGAN 超分引擎测试（vendored 架构 / 加载推理 / 分块 / 路由）。

策略：CPU + tiny 架构覆盖全链路（结构对齐用小参数验证，加载用
torch.save 的 tiny state_dict），不依赖 64MB 官方权重——官方权重的
端到端属 e2e（缺权重 skip，见 TestOfficialWeightsE2E）。
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from core.exceptions import SupervisedEngineError  # noqa: E402
from core.interfaces_supervised import TaskType  # noqa: E402
from models.supervised.engines.super_realesrgan import (  # noqa: E402
    RealEsrganEngine,
    arch_config_from_name,
    get_torch_archs,
)
from models.supervised.engines.super_router import SuperRouterEngine  # noqa: E402

# tiny 架构参数（与官方权重结构同型，仅规模缩小）
_TINY_RRDB = {"num_feat": 16, "num_block": 1, "num_grow_ch": 8}


def _rand_bgr(h: int, w: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _save_tiny_rrdb(tmp_path, fname: str, scale: int = 4, wrap: str | None = None):
    """构造 tiny RRDBNet 并保存 state_dict（可选官方历史包裹格式）。

    末层 bias 置 0.5：未训练网络默认初始化输出以负值为主，clamp(0,1) 后
    近乎全黑——加偏置让前向输出非零，供分块覆盖率断言使用。
    """
    archs = get_torch_archs()
    torch.manual_seed(0)
    net = archs["rrdbnet"](num_in_ch=3, num_out_ch=3, scale=scale, **_TINY_RRDB)
    with torch.no_grad():
        net.conv_last.bias.fill_(0.5)
    state = net.state_dict()
    if wrap:
        state = {wrap: state}
    path = tmp_path / fname
    torch.save(state, str(path))
    return str(path), net


# ========================== 架构参数推断（纯函数） ========================== #


class TestArchConfigFromName:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fname,arch,scale,extra",
        [
            ("RealESRGAN_x4plus.pth", "rrdbnet", 4, {"num_block": 23}),
            ("RealESRGAN_x2plus.pth", "rrdbnet", 2, {"num_block": 23}),
            ("RealESRGAN_x4plus_anime_6B.pth", "rrdbnet", 4, {"num_block": 6}),
            ("realesr-general-x4v3.pth", "srvgg", 4, {"num_conv": 32}),
            ("随便命名.pth", "rrdbnet", 4, {"num_block": 23}),  # 未识别回退 x4plus
        ],
    )
    def test_first_candidate(self, fname, arch, scale, extra):
        cand = arch_config_from_name(fname)[0]
        assert cand["arch"] == arch
        assert cand["scale"] == scale
        for k, v in extra.items():
            assert cand[k] == v

    @pytest.mark.unit
    def test_unknown_name_has_fallback_candidates(self):
        cands = arch_config_from_name("mystery.pth")
        assert len(cands) >= 2  # strict load 失败时可逐候选自愈


# ================================ 网络结构 ================================= #


class TestVendoredArchitectures:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "scale,out_hw", [(4, 32), (2, 16)]
    )
    def test_rrdbnet_forward_shape(self, scale, out_hw):
        net = get_torch_archs()["rrdbnet"](
            num_in_ch=3, num_out_ch=3, scale=scale, **_TINY_RRDB
        )
        y = net(torch.rand(1, 3, 8, 8))
        assert y.shape == (1, 3, out_hw, out_hw)

    @pytest.mark.unit
    def test_srvggnet_forward_shape(self):
        net = get_torch_archs()["srvgg"](
            num_in_ch=3, num_out_ch=3, num_feat=16, num_conv=3,
            upscale=4, act_type="prelu",
        )
        y = net(torch.rand(1, 3, 8, 8))
        assert y.shape == (1, 3, 32, 32)


# ================================ 引擎契约 ================================= #


class TestEngineContracts:
    @pytest.mark.unit
    def test_infer_not_loaded_raises(self):
        eng = RealEsrganEngine()
        with pytest.raises(SupervisedEngineError) as ei:
            eng.infer(_rand_bgr(8, 8))
        assert ei.value.details.get("task") == TaskType.SUPER.value

    @pytest.mark.unit
    def test_load_missing_raises(self, tmp_path):
        eng = RealEsrganEngine()
        with pytest.raises(SupervisedEngineError) as ei:
            eng.load(str(tmp_path / "nonexistent.pth"))
        assert ei.value.details.get("task") == TaskType.SUPER.value

    @pytest.mark.unit
    def test_load_garbage_weights_raises(self, tmp_path):
        path = tmp_path / "RealESRGAN_x4plus.pth"
        torch.save({"not_a_state_dict": torch.zeros(1)}, str(path))
        eng = RealEsrganEngine()
        with pytest.raises(SupervisedEngineError):
            eng.load(str(path), device="cpu")

    @pytest.mark.unit
    def test_unsupported_ext_rejected_by_load(self, tmp_path):
        # 后缀不归本引擎管（路由层职责），但直接误用时给出可读错误
        path = tmp_path / "weights.onnx"
        path.write_bytes(b"\x00")
        eng = RealEsrganEngine()
        with pytest.raises(SupervisedEngineError):
            eng.load(str(path), device="cpu")


class TestEngineInfer:
    @pytest.fixture()
    def x4_weights(self, tmp_path):
        path, _net = _save_tiny_rrdb(tmp_path, "RealESRGAN_x4plus.pth", scale=4)
        return path

    @pytest.mark.unit
    def test_infer_shape_dtype_and_metadata(self, x4_weights):
        eng = RealEsrganEngine()
        eng.load(x4_weights, device="cpu", arch_overrides=_TINY_RRDB)
        res = eng.infer(_rand_bgr(40, 40))
        hr = res.extra["hr_image"]
        assert hr.shape == (160, 160, 3)
        assert hr.dtype == np.uint8
        assert res.task == TaskType.SUPER
        assert res.labels == ("super_resolved",)
        assert res.extra["backend"] == "realesrgan"
        assert res.extra["scale"] == 4
        assert eng.scale == 4

    @pytest.mark.unit
    def test_infer_x2(self, tmp_path):
        path, _ = _save_tiny_rrdb(tmp_path, "RealESRGAN_x2plus.pth", scale=2)
        eng = RealEsrganEngine()
        eng.load(path, device="cpu", arch_overrides=_TINY_RRDB)
        res = eng.infer(_rand_bgr(30, 30))
        assert res.extra["hr_image"].shape == (60, 60, 3)
        assert eng.scale == 2

    @pytest.mark.unit
    def test_wrapped_params_unwrapped(self, tmp_path):
        path, _ = _save_tiny_rrdb(
            tmp_path, "RealESRGAN_x4plus.pth", scale=4, wrap="params"
        )
        eng = RealEsrganEngine()
        eng.load(path, device="cpu", arch_overrides=_TINY_RRDB)
        assert eng.infer(_rand_bgr(8, 8)).extra["hr_image"].shape == (32, 32, 3)

    @pytest.mark.unit
    def test_gray_input_promoted(self, x4_weights):
        eng = RealEsrganEngine()
        eng.load(x4_weights, device="cpu", arch_overrides=_TINY_RRDB)
        res = eng.infer(np.full((20, 20), 128, dtype=np.uint8))
        assert res.extra["hr_image"].shape == (80, 80, 3)

    @pytest.mark.unit
    def test_none_input_raises(self, x4_weights):
        eng = RealEsrganEngine()
        eng.load(x4_weights, device="cpu", arch_overrides=_TINY_RRDB)
        with pytest.raises(SupervisedEngineError):
            eng.infer(None)

    @pytest.mark.unit
    def test_tiled_output_matches_scale(self, x4_weights):
        eng = RealEsrganEngine()
        eng.load(
            x4_weights, device="cpu", arch_overrides=_TINY_RRDB,
            tile_size=64, tile_pad=8,
        )
        res = eng.infer(_rand_bgr(100, 90, seed=1))  # > tile_size → 分块路径
        hr = res.extra["hr_image"]
        assert hr.shape == (400, 360, 3)
        # 末层 bias=0.5 的网络输出应基本非零——画布存在未写区域则显著低
        assert float((hr > 0).mean()) > 0.99

    @pytest.mark.unit
    def test_unload_releases(self, x4_weights):
        eng = RealEsrganEngine()
        eng.load(x4_weights, device="cpu", arch_overrides=_TINY_RRDB)
        eng.unload()
        assert eng._model is None
        with pytest.raises(SupervisedEngineError):
            eng.infer(_rand_bgr(8, 8))


# ============================== SUPER 路由层 =============================== #


class TestSuperRouter:
    @pytest.mark.unit
    def test_fresh_infer_raises(self):
        with pytest.raises(SupervisedEngineError) as ei:
            SuperRouterEngine().infer(_rand_bgr(8, 8))
        assert ei.value.details.get("task") == TaskType.SUPER.value

    @pytest.mark.unit
    def test_unsupported_ext_raises(self, tmp_path):
        p = tmp_path / "weights.onnx"
        p.write_bytes(b"\x00")
        with pytest.raises(SupervisedEngineError) as ei:
            SuperRouterEngine().load(str(p))
        assert ".pth" in str(ei.value) and ".pb" in str(ei.value)

    @pytest.mark.unit
    def test_missing_pth_raises(self, tmp_path):
        with pytest.raises(SupervisedEngineError):
            SuperRouterEngine().load(str(tmp_path / "nope.pth"))

    @pytest.mark.unit
    def test_pth_routes_to_realesrgan(self, tmp_path):
        path, _ = _save_tiny_rrdb(tmp_path, "RealESRGAN_x4plus.pth", scale=4)
        router = SuperRouterEngine()
        router.load(path, device="cpu", arch_overrides=_TINY_RRDB)
        assert router.backend_name == "RealEsrganEngine"
        assert router.scale == 4
        res = router.infer(_rand_bgr(24, 24))
        assert res.extra["hr_image"].shape == (96, 96, 3)
        assert res.extra["backend"] == "realesrgan"
        router.unload()
        assert router.backend_name == ""

    @pytest.mark.unit
    def test_pb_routes_to_super_cv2(self, tmp_path, monkeypatch):
        from models.supervised.engines.super_cv2 import SuperCv2Engine

        loaded: dict = {}
        monkeypatch.setattr(
            SuperCv2Engine, "load",
            lambda self, w, device="cuda", **kw: loaded.update(path=w),
        )
        router = SuperRouterEngine()
        router.load(str(tmp_path / "EDSR_x4.pb"), device="cpu")
        assert router.backend_name == "SuperCv2Engine"
        assert loaded["path"].endswith("EDSR_x4.pb")

    @pytest.mark.unit
    def test_registry_resolves_router(self):
        from models.supervised import get_default_registry, get_engine
        from models.supervised.engines import register_all_engines

        register_all_engines()
        reg = get_default_registry()
        reg.clear_cache(TaskType.SUPER)
        engine = get_engine(TaskType.SUPER)
        assert isinstance(engine, SuperRouterEngine)


# ============================ 官方权重 e2e（可选） ========================== #


class TestOfficialWeightsE2E:
    """有官方权重（AVA_REALESRGAN_X4PLUS 环境变量指向 .pth）才跑。"""

    @pytest.mark.e2e
    def test_official_x4plus(self, tmp_path):
        import os

        weights = os.environ.get("AVA_REALESRGAN_X4PLUS", "")
        if not os.path.exists(weights):
            pytest.skip("未设置 AVA_REALESRGAN_X4PLUS 或文件不存在")
        eng = RealEsrganEngine()
        eng.load(weights, device="cuda" if torch.cuda.is_available() else "cpu")
        res = eng.infer(_rand_bgr(64, 64))
        assert res.extra["hr_image"].shape == (256, 256, 3)
