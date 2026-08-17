"""W11 审查 v2 P1-5 修复回归：_sqrtm 对非对称协方差积的矩阵平方根。

缺陷（修复前）：fid_score 计算 FID 时对 P = Σ_g·Σ_r（两个对称协方差之
积，一般非对称）直接 eigh——eigh 只读下三角，等价把 P 偷换成另一个对称
矩阵，Tr(√P) 系统性偏差：同分布 FID 被抬高 3~5 倍，小样本下可为负
（FID 数学上恒 ≥ 0，因其等于 Wasserstein-2 距离平方）。

修复后语义：
- 对称矩阵：维持 eigh 快路径（含 eps 地板，既有行为不变）；
- 非对称矩阵：np.linalg.eig 真矩阵平方根 V·diag(√λ)·V⁻¹（λ 取实部、
  微负 clip 0），与 scipy.linalg.sqrtm 数值一致（trace 项 rel err < 1e-6）。
"""
from __future__ import annotations

import numpy as np
import pytest

import evaluation.generative_metrics as gm


def _psd(rng: np.random.RandomState, d: int) -> np.ndarray:
    """随机对称正定矩阵（满秩：GGᵀ + 0.5I）。"""
    g = rng.randn(d, d)
    return g @ g.T + 0.5 * np.eye(d)


def _trace_term(a: np.ndarray, b: np.ndarray, covmean: np.ndarray) -> float:
    """FID 协方差 trace 项 Tr(A + B - 2·covmean)。"""
    return float(np.real(np.trace(a + b - 2.0 * covmean)))


# ============================== (a) 同分布 FID≈0 ============================== #
@pytest.mark.unit
def test_fid_same_distribution_nonnegative_and_small(monkeypatch):
    """两组同参数高斯特征 → FID ≥ 0 且处于抽样噪声量级。

    d=16, n=100：修复后样本 FID 实测约 0.9~1.7（总体 FID=0，残差纯属
    有限样本协方差/均值噪声），容差 3.0 留约 2 倍余量；旧 eigh 直开
    非对称积的实现在本 seed 实测约 -0.13（负 FID）。
    """
    rng = np.random.RandomState(8)
    d, n = 16, 100
    mu = rng.randn(d) * 0.5
    a0 = rng.randn(d, d)
    cov = a0 @ a0.T / d + 0.1 * np.eye(d)  # 各向异性协方差
    gen_feats = rng.multivariate_normal(mu, cov, size=n)
    real_feats = rng.multivariate_normal(mu, cov, size=n)

    feats = iter([gen_feats, real_feats])
    monkeypatch.setattr(
        gm, "_extract_features", lambda images, device="cpu": next(feats)
    )
    dummy = [np.zeros((2, 2, 3), dtype=np.uint8)] * n

    fid = gm.fid_score(dummy, dummy)

    assert fid >= 0.0, f"FID 数学上恒 ≥ 0，实为 {fid}"
    assert fid < 3.0, f"同分布 FID 应处于抽样噪声量级，实为 {fid}"


# ============================== (b) scipy 对照 ============================== #
@pytest.mark.unit
@pytest.mark.parametrize("seed,d", [(11, 8), (23, 12), (37, 16)])
def test_sqrtm_trace_term_matches_scipy(seed, d):
    """随机 PSD 对的 FID trace 项与 scipy.linalg.sqrtm 参考 rel err < 1e-6。"""
    sla = pytest.importorskip("scipy").linalg

    rng = np.random.RandomState(seed)
    a = _psd(rng, d)
    b = _psd(rng, d)
    p = a @ b  # 非对称

    ref_covmean = np.real(sla.sqrtm(p))
    ref_trace = _trace_term(a, b, ref_covmean)

    covmean, ok = gm._sqrtm(p)
    assert ok is True
    got_trace = _trace_term(a, b, np.real(covmean))

    rel = abs(got_trace - ref_trace) / max(abs(ref_trace), 1e-30)
    assert rel < 1e-6, (
        f"trace 项相对误差 {rel:.3e} 超 1e-6（ref={ref_trace:.6f}, "
        f"got={got_trace:.6f}）"
    )


# ============================== (c) 非对称积回归 ============================== #
@pytest.mark.unit
def test_sqrtm_nonsymmetric_beats_old_eigh_formula():
    """非对称积回归：新实现误差 < 旧 eigh 直开公式误差的 1%（写死量化）。"""
    sla = pytest.importorskip("scipy").linalg

    rng = np.random.RandomState(5)
    d = 16
    a = _psd(rng, d)
    b = _psd(rng, d)
    p = a @ b  # 两个不同 PSD 之积：非对称

    # 参考：scipy 真矩阵平方根
    ref_trace = _trace_term(a, b, np.real(sla.sqrtm(p)))

    # 旧公式（测试内复刻修复前实现）：eigh 直接开非对称 P
    w_old, v_old = np.linalg.eigh(p)
    old_covmean = v_old @ np.diag(np.sqrt(np.maximum(w_old, 0) + 1e-6)) @ v_old.T
    old_trace = _trace_term(a, b, old_covmean)

    # 修复后实现
    covmean, ok = gm._sqrtm(p)
    assert ok is True
    new_trace = _trace_term(a, b, np.real(covmean))

    err_old = abs(old_trace - ref_trace)
    err_new = abs(new_trace - ref_trace)
    assert err_old > 0.1, f"旧公式须与参考有实质偏差（校准值 ≈5），实为 {err_old}"
    assert err_new < 0.01 * err_old, (
        f"新误差 {err_new:.3e} 未小于旧误差 {err_old:.6f} 的 1%"
    )
