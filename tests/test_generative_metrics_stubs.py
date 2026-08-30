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
    """注入假 lpips 模块走 LPIPS 主路径：net="alex" 构造、[-1,1] NCHW 张量、
    逐对前向取均值、长度不齐取 min（:157、:164-179）。"""
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

    gen = [_img(seed=1), _img(seed=2)]          # 2 张
    tgt = [_img(seed=3), _img(seed=4), _img(seed=5)]  # 3 张 → n=min=2

    loss = gm.perceptual_loss(gen, tgt)
    assert ctor_kw == {"net": "alex"}
    assert len(seen_tensors) == 2  # 只取前 2 对
    for a, b in seen_tensors:
        assert a.shape == (1, 3, 6, 8) and b.shape == (1, 3, 6, 8)  # NCHW
        assert a.dtype == torch.float32
        assert float(a.min()) >= -1.0 and float(a.max()) <= 1.0     # [-1,1]
    assert loss == pytest.approx(0.25)


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
