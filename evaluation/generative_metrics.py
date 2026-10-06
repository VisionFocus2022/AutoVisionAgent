"""
FID / 感知损失评估（FR-B2）

- fid_score：Fréchet Inception Distance（生成图 vs 真实图分布距离）
- perceptual_loss：LPIPS 感知损失（逐图对相似度）
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _to_numpy(images: Sequence, resize: bool = True) -> np.ndarray:
    """统一转 [N, H, W, 3] float32 [0,1]。

    E6（2026-10-06 三轮审查）：异尺寸输入此前 np.stack 直接 ValueError——
    工业数据集常见混合分辨率（多相机/多批次）。resize=True 时以首图为
    基准统一 PIL BILINEAR；灰度（HxW 2 维）一并 expand 到 3 通道（工业
    灰度相机输入防御）。resize=False 保留严格模式（异尺寸抛 ValueError，
    供测试断言旧行为）。
    """
    arrs = []
    for img in images:
        if isinstance(img, str):
            from PIL import Image
            arr = np.asarray(Image.open(img).convert("RGB"), dtype=np.float32) / 255.0
        else:
            arr = np.asarray(img, dtype=np.float32)
            if arr.max() > 1.5:
                arr = arr / 255.0
        # E6：灰度 → 3 通道（convert("RGB") 路径天然 3 通道，仅 ndarray 分支需要）
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        arrs.append(arr)
    if not arrs:
        return np.zeros((0, 0, 0, 3), dtype=np.float32)
    if resize:
        base_hw = arrs[0].shape[:2]
        aligned = [arrs[0]]
        from PIL import Image
        for arr in arrs[1:]:
            if arr.shape[:2] != base_hw:
                pil = Image.fromarray(
                    (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
                )
                pil = pil.resize((base_hw[1], base_hw[0]), Image.BILINEAR)
                arr = np.asarray(pil, dtype=np.float32) / 255.0
            aligned.append(arr)
        arrs = aligned
    return np.stack(arrs)


# E13（2026-10-06 三轮审查）：InceptionV3 按 device 缓存——此前
# _extract_features 每次调用完整构建模型（fid_score 一次调用建两次、
# 下两次 IMAGENET 权重，E5 样本帽提 200 后开销放大 10 倍）。
_INCEPTION_CACHE: dict[str, object] = {}


def _reset_inception_cache() -> None:
    """E13 测试钩子：清空模型缓存（替身注入前/跨用例防污染）。"""
    _INCEPTION_CACHE.clear()


def _get_inception_model(device: str = "cpu"):
    """E13：构建（或复用）去分类头的 InceptionV3。"""
    if device in _INCEPTION_CACHE:
        return _INCEPTION_CACHE[device]
    import torch
    from torchvision.models import inception_v3

    # torchvision >= 0.13 使用 weights= API（R3-15 迁移）
    try:
        from torchvision.models import Inception_V3_Weights
        model = inception_v3(
            weights=Inception_V3_Weights.IMAGENET1K_V1,
            transform_input=False,
            aux_logits=True,
        )
    except (ImportError, TypeError):
        # 旧版 torchvision (< 0.13) 回退
        model = inception_v3(pretrained=True, transform_input=False, aux_logits=True)
    model.fc = torch.nn.Identity()  # 去掉分类头
    model.eval()
    model.to(device)
    _INCEPTION_CACHE[device] = model
    return model


def fid_score(
    generated: Sequence,
    real: Sequence,
    device: str = "cpu",
) -> float:
    """
    计算 Fréchet Inception Distance。

    FID = ||μ_g - μ_r||² + Tr(Σ_g + Σ_r - 2(Σ_g·Σ_r)^0.5)

    Args:
        generated: 生成图像序列。
        real: 真实图像序列。

    Returns:
        FID 标量（越低越好，0=分布完全相同）。
    """
    gen_arr = _to_numpy(generated)
    real_arr = _to_numpy(real)

    gen_feats = _extract_features(gen_arr, device)
    real_feats = _extract_features(real_arr, device)

    mu_g, sigma_g = gen_feats.mean(axis=0), np.cov(gen_feats, rowvar=False)
    mu_r, sigma_r = real_feats.mean(axis=0), np.cov(real_feats, rowvar=False)

    diff = mu_g - mu_r
    covmean, _ = _sqrtm(sigma_g @ sigma_r)
    if np.iscomplexobj(covmean):
        covmean = covmean.real

    fid = diff @ diff + np.trace(sigma_g + sigma_r - 2 * covmean)
    # E20（2026-10-06 三轮审查）：trace 项数值误差可微负（-1e-16 量级）
    # 致 FID 显示 -0.00xx——数学上 FID ≥ 0，钳位防误读。
    return float(max(fid, 0.0))


def _sqrtm(mat: np.ndarray, eps: float = 1e-6) -> tuple[np.ndarray, bool]:
    """numpy 版矩阵开方（替代 scipy.linalg.sqrtm）。

    - 对称矩阵：eigh 快路径（含 eps 地板，行为与历史版本一致）。
    - 非对称矩阵（FID 中 P = Σ_g·Σ_r 的积即此类）：np.linalg.eig 真矩阵
      平方根 P = V·diag(λ)·V⁻¹ → √P = V·diag(√λ)·V⁻¹。两个 PSD 之积与
      A^{1/2}BA^{1/2} 相似，特征值实非负，故 λ 取实部、微负 clip 0 后
      结果与 scipy.linalg.sqrtm 数值一致（不可用 eigh：其只读下三角，
      对非对称输入等价偷换矩阵，W11 实测 FID 恒偏差且可为负）。
    """
    from numpy.linalg import eig, eigh, inv

    scale = float(np.abs(mat).max()) if mat.size else 0.0
    if np.allclose(mat, mat.T, rtol=1e-10, atol=1e-12 * max(1.0, scale)):
        # 对称矩阵
        w, v = eigh(mat)
        w = np.maximum(w, 0)  # 裁剪负值
        sqrt_w = np.sqrt(w + eps)
        return v @ np.diag(sqrt_w) @ v.T, True

    # 非对称：真（非对称）矩阵平方根
    w, v = eig(mat)
    w = np.clip(w.real, 0.0, None)  # 特征值取实部、微负 clip 0
    root = v @ np.diag(np.sqrt(w)) @ inv(v)
    if np.iscomplexobj(root) and np.allclose(
        root.imag, 0.0, atol=1e-8 * max(1.0, scale)
    ):
        root = root.real  # 虚部为数值残差时回落实矩阵
    return root, True


# E13 同批：LPIPS 网络缓存（此前每次 perceptual_loss 重建 net="alex"）
_LPIPS_CACHE: dict[str, object] = {}


def _get_lpips_model(device: str = "cpu"):
    """E13：构建（或复用）LPIPS 网络。"""
    if device in _LPIPS_CACHE:
        return _LPIPS_CACHE[device]
    import lpips

    model = lpips.LPIPS(net="alex").to(device)
    model.eval()
    _LPIPS_CACHE[device] = model
    return model


def perceptual_loss(
    generated: Sequence,
    target: Sequence,
    device: str = "cpu",
    pairing: str = "nearest",
) -> float:
    """
    LPIPS 感知损失。

    Args:
        generated: 生成图像序列。
        target: 目标图像序列。
        device: 计算设备。
        pairing: 配对语义（E4，2026-10-06 三轮审查）——
            "nearest"（默认）：每张生成图对全部目标图求 LPIPS 取最小
            （最近邻），再对生成图取均值。目录输入场景 gen/real 文件
            顺序无配对关系（os.walk 顺序甚至不确定），按下标配对语义
            错误；最近邻度量"生成分布到真实分布的最短感知距离"。
            "index"：旧语义（按下标 gen[i] vs target[i]，n=min 截断），
            保留给确有等长配对语义的调用方作逃生门。

    Returns:
        平均 LPIPS 损失（越低越相似）。
    """
    if pairing not in ("nearest", "index"):
        raise ValueError(f"未知配对模式: {pairing!r}（支持 nearest/index）")

    try:
        import lpips  # noqa: F401
        import torch
    except ImportError:
        # 回退：L2 像素损失（E6 尺寸对齐后异尺寸不崩）
        gen_arr = _to_numpy(generated)
        tgt_arr = _to_numpy(target)
        if pairing == "index":
            n = min(len(gen_arr), len(tgt_arr))
            gen_arr, tgt_arr = gen_arr[:n], tgt_arr[:n]
        return float(np.mean((gen_arr - tgt_arr) ** 2))

    model = _get_lpips_model(device)

    gen_arr = _to_numpy(generated)
    tgt_arr = _to_numpy(target)

    losses = []
    with torch.no_grad():
        if pairing == "index":
            # E4 兼容路径：旧按下标配对
            n = min(len(gen_arr), len(tgt_arr))
            for i in range(n):
                gen_t = _to_tensor_lpips(gen_arr[i], device)
                tgt_t = _to_tensor_lpips(tgt_arr[i], device)
                loss = model(gen_t, tgt_t)
                losses.append(float(loss.item()))
        else:
            # E4 默认：最近邻——每 gen 对全部 target 取 min
            tgt_tensors = [
                _to_tensor_lpips(t, device) for t in tgt_arr
            ]
            for g in gen_arr:
                gen_t = _to_tensor_lpips(g, device)
                pair_vals = [
                    float(model(gen_t, t_t).item()) for t_t in tgt_tensors
                ]
                losses.append(min(pair_vals) if pair_vals else 0.0)
    return float(np.mean(losses)) if losses else 0.0


def _to_tensor_lpips(arr: np.ndarray, device: str):
    """转 [-1,1] NCHW 张量（LPIPS 约定）。"""
    import torch
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).float()
    t = t * 2 - 1  # [0,1] → [-1,1]
    return t.to(device)


__all__ = ["fid_score", "perceptual_loss"]
