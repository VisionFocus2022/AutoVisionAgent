"""evaluation/generative_metrics.py 替身补测（W14-C4：53% → 目标 ≥93%）。

诚实边界（不装真模型）：
- _extract_features / fid_score：InceptionV3 以替身注入（monkeypatch
  torchvision.models.inception_v3），覆盖的是取特征的编排管线（transforms
  流水线、逐图前向、fc 替换、no_grad、stack）；不验证真 InceptionV3 数值，
  真 FID 数值等价性需下载 IMAGENET1K_V1 权重，离线环境不伪造。
- fid_score 复数 covmean 分支（:103）：FID 的两个输入协方差恒为 PSD，其积
  的矩阵平方根数学上恒实——该分支是对不可达输入的防御，经注入 _sqrtm 桩
  覆盖（若走不到 float() 转换会 TypeError，可证分支确实执行）。
- perceptual_loss LPIPS 主路径（:157、:164-179）：注入假 lpips 模块
  （真实环境未装 lpips，生产代码本就设计为回退 L2）；_to_tensor_lpips 用
  真 torch 张量运算，无模型依赖。
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")
pytest.importorskip("PIL")

import evaluation.generative_metrics as gm  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_model_caches():
    """E13：每用例前后清模型缓存——替身注入残留会跨用例污染真模型引用。"""
    gm._INCEPTION_CACHE.clear()
    gm._LPIPS_CACHE.clear()
    yield
    gm._INCEPTION_CACHE.clear()
    gm._LPIPS_CACHE.clear()


def _img(h=6, w=8, seed=0):
    rng = np.random.default_rng(seed)
    return rng.random((h, w, 3)).astype(np.float32)


# ============================== _to_numpy 文件路径分支 ============================== #
@pytest.mark.unit
def test_to_numpy_from_image_file_paths(tmp_path):
    """str 路径 → PIL 打开转 [0,1] float32（:20-21）。"""
    from PIL import Image

    paths = []
    for i, shade in enumerate((0, 255)):
        p = tmp_path / f"img{i}.png"
        Image.fromarray(
            np.full((4, 6, 3), shade, dtype=np.uint8), "RGB"
        ).save(p)
        paths.append(str(p))

    arr = gm._to_numpy(paths)
    assert arr.shape == (2, 4, 6, 3)
    assert arr.dtype == np.float32
    assert arr[0].max() == pytest.approx(0.0)   # 黑图 → 0
    assert arr[1].min() == pytest.approx(1.0)   # 白图 → 1


# ============================== _extract_features（替身 InceptionV3） ============================== #
class _FakeInception:
    """替身模型：fc 可替换、eval/to 链式、前向返回 [1, 2048] 张量。"""

    def __init__(self):
        self.fc = None
        self.calls = 0

    def eval(self):
        return self

    def to(self, device):
        return self

    def __call__(self, tensor):
        assert tensor.ndim == 4 and tensor.shape[1] == 3  # NCHW
        self.calls += 1
        return torch.full((1, 2048), float(self.calls))


@pytest.mark.unit
def test_extract_features_stubbed_inception_weights_api(monkeypatch):
    """torchvision>=0.13 weights= API 路径：fc 替 Identity、逐图前向、
    输出堆叠 [N, 2048]（:35-71 主路径）。"""
    import torchvision.models as tvm

    fake = _FakeInception()
    seen = {}

    def _factory(**kw):
        seen.update(kw)
        return fake

    monkeypatch.setattr(tvm, "inception_v3", _factory)
    feats = gm._extract_features(np.stack([_img(seed=1), _img(seed=2)]))
    assert seen["weights"] is tvm.Inception_V3_Weights.IMAGENET1K_V1
    assert seen["transform_input"] is False and seen["aux_logits"] is True
    assert isinstance(fake.fc, torch.nn.Identity)  # 分类头已去
    assert fake.calls == 2  # 逐图前向
    assert feats.shape == (2, 2048)
    np.testing.assert_allclose(feats[0], np.full(2048, 1.0), rtol=0)
    np.testing.assert_allclose(feats[1], np.full(2048, 2.0), rtol=0)


@pytest.mark.unit
def test_extract_features_old_torchvision_fallback(monkeypatch):
    """weights= kwarg 抛 TypeError → 回退 pretrained=True 旧 API（:46-48）。"""
    import torchvision.models as tvm

    fake = _FakeInception()
    seen = {}

    def _factory(**kw):
        if "weights" in kw:
            raise TypeError("unexpected keyword argument 'weights'")
        seen.update(kw)
        return fake

    monkeypatch.setattr(tvm, "inception_v3", _factory)
    feats = gm._extract_features(np.stack([_img()]))
    assert seen == {"pretrained": True, "transform_input": False,
                    "aux_logits": True}
    assert feats.shape == (1, 2048)


# ============================== fid_score（_sqrtm 桩注入） ============================== #
@pytest.mark.unit
def test_fid_score_complex_covmean_takes_real(monkeypatch):
    """covmean 为复数 → 取实部（:103）。PSD 输入下该分支数学上不可达，
    经 _sqrtm 桩注入覆盖：若不取实部，float() 对复数必 TypeError。"""
    monkeypatch.setattr(
        gm, "_sqrtm",
        lambda mat, eps=1e-6: (np.full((2, 2), 2.0 + 1j), True),
    )

    gen_black = [np.zeros((4, 4, 3), dtype=np.float32)]   # _to_numpy → 全 0
    real_half = [np.full((4, 4, 3), 0.5, dtype=np.float32)]  # → 全 0.5
    feats = {
        "g": np.zeros((2, 2)),                     # mu=[0,0]，cov=0
        "r": np.array([[1., 1.], [3., 3.]]),       # mu=[2,2]，cov=[[2,2],[2,2]]
    }

    def _fake_extract(images, device="cpu"):
        return feats["g"] if images.max() == 0 else feats["r"]

    monkeypatch.setattr(gm, "_extract_features", _fake_extract)
    fid = gm.fid_score(gen_black, real_half)
    # diff@diff=8；covmean.real=2 → trace(0+Σr-2·2)=trace([[-2,-2],[-2,-2]])=-4
    assert fid == pytest.approx(4.0)
    assert isinstance(fid, float)


@pytest.mark.unit
def test_sqrtm_complex_dtype_with_negligible_imag_falls_back_to_real():
    """纯旋转矩阵（特征值 ±i）→ 开方结果复数 dtype 但虚部≈0 → 回落实矩阵
    （:136）。"""
    rot = np.array([[0.0, 1.0], [-1.0, 0.0]])
    root, ok = gm._sqrtm(rot)
    assert ok is True
    assert not np.iscomplexobj(root)  # 回落实 dtype
    np.testing.assert_allclose(root, 0.0)  # λ 取实部为 0 → 平方根为零矩阵


# ============================== perceptual_loss（假 lpips 模块） ============================== #
@pytest.mark.unit
def test_perceptual_loss_fake_lpips_module(monkeypatch):
    """注入假 lpips 模块走 LPIPS 主路径：net="alex" 构造、[-1,1] NCHW 张量。

    E4（2026-10-06 三轮审查）后默认 nearest 配对：2 gen × 3 tgt =
    6 次前向（每 gen 对全部 tgt），模型返回固定 0.25 → 均值 0.25。"""
    seen_tensors = []

    class _Model:
        def to(self, device):
            return self

        def eval(self):
            return self

        def __call__(self, a, b):
            seen_tensors.append((a, b))
            return torch.tensor(0.25)

    ctor_kw = {}

    def _ctor(net="alex"):
        ctor_kw["net"] = net
        return _Model()

    fake_mod = types.ModuleType("lpips")
    fake_mod.LPIPS = _ctor
    monkeypatch.setitem(sys.modules, "lpips", fake_mod)

    gen = [_img(seed=1), _img(seed=2)]               # 2 张
    tgt = [_img(seed=3), _img(seed=4), _img(seed=5)]  # 3 张

    loss = gm.perceptual_loss(gen, tgt)
    assert ctor_kw == {"net": "alex"}
    # E4 nearest：每张 gen 对全部 3 张 tgt → 2×3 = 6 次前向
    assert len(seen_tensors) == 6
    for a, b in seen_tensors:
        assert a.shape == (1, 3, 6, 8) and b.shape == (1, 3, 6, 8)  # NCHW
        assert a.dtype == torch.float32
        assert float(a.min()) >= -1.0 and float(a.max()) <= 1.0     # [-1,1]
    assert loss == pytest.approx(0.25)


@pytest.mark.unit
def test_perceptual_loss_index_pairing_backward_compat(monkeypatch):
    """E4 兼容锚：pairing="index" 保持旧按下标配对语义（n=min 截断）。"""
    seen_tensors = []

    class _Model:
        def to(self, device):
            return self

        def eval(self):
            return self

        def __call__(self, a, b):
            seen_tensors.append((a, b))
            return torch.tensor(0.25)

    fake_mod = types.ModuleType("lpips")
    fake_mod.LPIPS = lambda net="alex": _Model()
    monkeypatch.setitem(sys.modules, "lpips", fake_mod)

    gen = [_img(seed=1), _img(seed=2)]
    tgt = [_img(seed=3), _img(seed=4), _img(seed=5)]

    loss = gm.perceptual_loss(gen, tgt, pairing="index")
    assert len(seen_tensors) == 2  # 旧语义：只取前 2 对
    assert loss == pytest.approx(0.25)


@pytest.mark.unit
def test_perceptual_loss_nearest_takes_min_per_gen(monkeypatch):
    """E4 核心：nearest 模式每 gen 取对全部 tgt 的最小值（可区分返回值验证）。"""
    # 假模型返回 |a_mean - b_mean|——可构造每 gen 与某张 tgt 最接近
    class _Model:
        def to(self, device):
            return self

        def eval(self):
            return self

        def __call__(self, a, b):
            return torch.tensor(abs(float(a.mean()) - float(b.mean())))

    fake_mod = types.ModuleType("lpips")
    fake_mod.LPIPS = lambda net="alex": _Model()
    monkeypatch.setitem(sys.modules, "lpips", fake_mod)

    # gen[0] 均值 0.2 → 最近 tgt（0.25）距离 0.05
    # gen[1] 均值 0.8 → 最近 tgt（0.75）距离 0.05
    gen = [
        np.full((4, 4, 3), 0.2, dtype=np.float32),
        np.full((4, 4, 3), 0.8, dtype=np.float32),
    ]
    tgt = [
        np.full((4, 4, 3), 0.25, dtype=np.float32),
        np.full((4, 4, 3), 0.5, dtype=np.float32),
        np.full((4, 4, 3), 0.75, dtype=np.float32),
    ]

    loss = gm.perceptual_loss(gen, tgt)
    assert loss == pytest.approx(0.05, abs=1e-4), "nearest 必须取每 gen 的最小距离"


@pytest.mark.unit
def test_perceptual_loss_invalid_pairing_raises():
    """E4：未知配对模式显式拒绝。"""
    with pytest.raises(ValueError, match="配对模式"):
        gm.perceptual_loss([_img()], [_img()], pairing="bogus")


@pytest.mark.unit
def test_to_tensor_lpips_range_and_shape():
    """[0,1] HWC → 2x-1 → [-1,1] NCHW float 张量（:184-187）。"""
    black = np.zeros((2, 2, 3), dtype=np.float32)
    t = gm._to_tensor_lpips(black, "cpu")
    assert t.shape == (1, 3, 2, 2)
    assert float(t.min()) == -1.0 and float(t.max()) == -1.0

    half = np.full((2, 2, 3), 0.5, dtype=np.float32)
    t2 = gm._to_tensor_lpips(half, "cpu")
    np.testing.assert_allclose(t2.numpy(), 0.0, rtol=0)


# ============== E13（2026-10-06 三轮审查）：模型缓存复用 ============== #


@pytest.mark.unit
def test_inception_model_cached_per_device(monkeypatch):
    """E13：同 device 两次调用返回同一实例（此前每次重建）。"""
    import torchvision.models as tvm

    built = []

    def _factory(**kw):
        m = _FakeInception()
        built.append(m)
        return m

    monkeypatch.setattr(tvm, "inception_v3", _factory)
    m1 = gm._get_inception_model("cpu")
    m2 = gm._get_inception_model("cpu")
    assert m1 is m2, "同 device 必须复用"
    assert len(built) == 1
    # 不同 device 各自缓存
    m3 = gm._get_inception_model("cuda")
    assert m3 is not m1
    assert len(built) == 2


@pytest.mark.unit
def test_extract_features_reuses_model_within_fid(monkeypatch):
    """E13 核心：fid_score 全流程下模型只构建一次（此前 gen/real 各一次=两次）。"""
    import torchvision.models as tvm

    build_count = {"n": 0}

    def _factory(**kw):
        build_count["n"] += 1
        return _FakeInception()

    monkeypatch.setattr(tvm, "inception_v3", _factory)

    def _fake_extract(images, device="cpu"):
        return gm._extract_features(images, device)

    # 直接观测：两次 _extract_features 共享一次构建
    feats1 = gm._extract_features(np.stack([_img(seed=1)]))
    feats2 = gm._extract_features(np.stack([_img(seed=2)]))
    assert build_count["n"] == 1, "两次特征提取必须共享同一模型实例"
    assert feats1.shape == (1, 2048) and feats2.shape == (1, 2048)


@pytest.mark.unit
def test_reset_inception_cache_clears(monkeypatch):
    """E13：_reset_inception_cache 后重新构建。"""
    import torchvision.models as tvm

    built = []

    def _factory(**kw):
        m = _FakeInception()
        built.append(m)
        return m

    monkeypatch.setattr(tvm, "inception_v3", _factory)
    m1 = gm._get_inception_model("cpu")
    gm._reset_inception_cache()
    m2 = gm._get_inception_model("cpu")
    assert m1 is not m2 and len(built) == 2


# ============== E6（2026-10-06 三轮审查）：尺寸对齐 ============== #


@pytest.mark.unit
def test_to_numpy_resizes_mixed_sizes():
    """E6：异尺寸输入统一 resize 到首图基准（此前 np.stack 崩）。"""
    big = np.ones((6, 8, 3), dtype=np.float32)
    small = np.zeros((4, 4, 3), dtype=np.float32)
    arr = gm._to_numpy([big, small])
    assert arr.shape == (2, 6, 8, 3), "以首图为基准对齐"


@pytest.mark.unit
def test_to_numpy_grayscale_expanded():
    """E6：灰度 HxW → 3 通道（工业灰度相机输入防御）。"""
    gray = np.full((4, 4), 0.5, dtype=np.float32)
    arr = gm._to_numpy([gray])
    assert arr.shape == (1, 4, 4, 3)


@pytest.mark.unit
def test_to_numpy_strict_mode_raises_on_mixed():
    """E6：resize=False 保留严格模式（旧行为锚）。"""
    big = np.ones((6, 8, 3), dtype=np.float32)
    small = np.zeros((4, 4, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        gm._to_numpy([big, small], resize=False)


@pytest.mark.unit
def test_perceptual_loss_l2_fallback_mixed_sizes_no_crash(monkeypatch):
    """E6：lpips 缺失回退 L2 + 异尺寸输入 → 对齐后不崩（此前直接崩）。"""
    monkeypatch.setitem(sys.modules, "lpips", None)  # import 失败路径
    gen = [np.ones((6, 8, 3), dtype=np.float32)]
    tgt = [np.zeros((4, 4, 3), dtype=np.float32)]
    val = gm.perceptual_loss(gen, tgt)
    assert isinstance(val, float) and val >= 0.0
