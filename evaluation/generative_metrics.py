"""
FID / 感知损失评估（FR-B2）

- fid_score：Fréchet Inception Distance（生成图 vs 真实图分布距离）
- perceptual_loss：LPIPS 感知损失（逐图对相似度）
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np


def _to_numpy(images: Sequence) -> np.ndarray:
    """统一转 [N, H, W, 3] float32 [0,1]。"""
    arrs = []
    for img in images:
        if isinstance(img, str):
            from PIL import Image
            arr = np.asarray(Image.open(img).convert("RGB"), dtype=np.float32) / 255.0
        else:
            arr = np.asarray(img, dtype=np.float32)
            if arr.max() > 1.5:
                arr = arr / 255.0
        arrs.append(arr)
    return np.stack(arrs)


def _extract_features(
    images: np.ndarray,
    device: str = "cpu",
) -> np.ndarray:
    """InceptionV3 池化特征 [N, 2048]。"""
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

    from torchvision import transforms

    tfm = transforms.Compose([
        transforms.ToPILImage(),
        transforms.Resize(299),
        transforms.CenterCrop(299),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
        ),
    ])

    feats = []
    with torch.no_grad():
        for arr in images:
            tensor = tfm(arr).unsqueeze(0).to(device)
            feat = model(tensor)
            feats.append(feat.cpu().numpy().squeeze(0))
    return np.stack(feats)


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
    return float(fid)


def _sqrtm(mat: np.ndarray, eps: float = 1e-6) -> Tuple[np.ndarray, bool]:
    """numpy 版矩阵开方（替代 scipy.linalg.sqrtm）。"""
    from numpy.linalg import eigvals, eigh

    # 对称矩阵
    w, v = eigh(mat)
    w = np.maximum(w, 0)  # 裁剪负值
    sqrt_w = np.sqrt(w + eps)
    return v @ np.diag(sqrt_w) @ v.T, True


def perceptual_loss(
    generated: Sequence,
    target: Sequence,
    device: str = "cpu",
) -> float:
    """
    LPIPS 感知损失（逐图对相似度）。

    Args:
        generated: 生成图像序列。
        target: 目标图像序列（等长）。

    Returns:
        平均 LPIPS 损失（越低越相似）。
    """
    try:
        import lpips
        import torch
    except ImportError:
        # 回退：L2 像素损失
        gen_arr = _to_numpy(generated)
        tgt_arr = _to_numpy(target)
        return float(np.mean((gen_arr - tgt_arr) ** 2))

    import torch

    model = lpips.LPIPS(net="alex").to(device)
    model.eval()

    gen_arr = _to_numpy(generated)
    tgt_arr = _to_numpy(target)
    n = min(len(gen_arr), len(tgt_arr))
    losses = []
    with torch.no_grad():
        for i in range(n):
            gen_t = _to_tensor_lpips(gen_arr[i], device)
            tgt_t = _to_tensor_lpips(tgt_arr[i], device)
            loss = model(gen_t, tgt_t)
            losses.append(float(loss.item()))
    return float(np.mean(losses))


def _to_tensor_lpips(arr: np.ndarray, device: str):
    """转 [-1,1] NCHW 张量（LPIPS 约定）。"""
    import torch
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).float()
    t = t * 2 - 1  # [0,1] → [-1,1]
    return t.to(device)


__all__ = ["fid_score", "perceptual_loss"]
