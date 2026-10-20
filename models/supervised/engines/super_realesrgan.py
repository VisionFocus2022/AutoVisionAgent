"""Real-ESRGAN 超分辨率引擎（xinntao/Real-ESRGAN，BSD-3-Clause）。

选型与实现方式：
- 官方 ``realesrgan`` PyPI 包硬依赖 ``basicsr``，其 1.4.2 在 import 时执行
  ``from torchvision.transforms.functional_tensor import ...``——该模块在
  torchvision 0.17 起已移除（本项目锁定 0.20.1+cu121），安装即不可用。
- 故本模块 vendor Real-ESRGAN 推理最小闭包：RRDBNet / SRVGGNetCompact
  网络定义（结构逐行对齐上游 realesrgan/archs/realesrgan_arch.py，授权
  BSD-3-Clause，版权见本文件头）+ 官方 .pth 权重加载 + 分块推理。
  零新增 pip 依赖（torch / numpy / opencv 均为既有依赖）。

权重来源（提醒：weights/ 目录被 .gitignore 排除、不入仓——换机器 /
新克隆后须先运行 scripts/download_realesrgan.py 重新拉取，或从离线供给
目录拷贝，再加载引擎）：
- RealESRGAN_x4plus.pth          RRDBNet x4 23 块（通用真实场景）
- RealESRGAN_x2plus.pth          RRDBNet x2 23 块
- RealESRGAN_x4plus_anime_6B.pth RRDBNet x4 6 块（轻量）
- realesr-general-x4v3.pth       SRVGGNetCompact x4（小模型）

契约与 super_cv2 对齐：load(.pth) → infer(lr) → DetectionResult，HR 图像经
extra["hr_image"] 返回（BGR uint8），预测页 / 视频超分流程零改动。
注册关系：TaskType.SUPER 由 super_router 按权重后缀路由（.pth/.pt → 本引擎；
本模块不直接 @register_engine，避免与 super_cv2 抢占同一 TaskType 槽位）。

上游版权声明（BSD-3-Clause）：
  Copyright (c) 2021, Xintao Wang
  Redistribution and use in source and binary forms, with or without
  modification, are permitted provided that the BSD-3-Clause conditions
  (as published at github.com/xinntao/Real-ESRGAN/blob/master/LICENSE)
  are met. 网络定义部分为上游代码的结构等价移植。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from inference.tiling_inferencer import compute_tiles
from models.supervised import AbstractTaskEngine

logger = logging.getLogger(__name__)

# 官方发布权重 → 架构参数候选（按文件名推断的优先序）。
# 每项: (arch, kwargs)；arch ∈ {"rrdbnet", "srvgg"}。
_RRDB_X4 = {"arch": "rrdbnet", "scale": 4, "num_feat": 64, "num_block": 23, "num_grow_ch": 32}
_RRDB_X4_ANIME = {"arch": "rrdbnet", "scale": 4, "num_feat": 64, "num_block": 6, "num_grow_ch": 32}
_RRDB_X2 = {"arch": "rrdbnet", "scale": 2, "num_feat": 64, "num_block": 23, "num_grow_ch": 32}
_SRVGG_X4V3 = {"arch": "srvgg", "scale": 4, "num_feat": 64, "num_conv": 32, "act_type": "prelu"}


def arch_config_from_name(fname: str) -> list[dict]:
    """按权重文件名给出架构参数候选（优先序）。

    纯函数（不触 torch），便于单测。文件名无法识别时回退通用 x4plus
    配置；调用方对候选逐个 strict load_state_dict，命中即采用——
    文件名与实际架构不符时仍可自愈。
    """
    f = os.path.basename(fname).lower()
    if "general-x4v3" in f or "general_x4v3" in f or "x4v3" in f:
        return [_SRVGG_X4V3, _RRDB_X4]
    if "anime" in f:
        return [_RRDB_X4_ANIME, _RRDB_X4]
    if "x2" in f:
        return [_RRDB_X2, _RRDB_X4]
    return [_RRDB_X4, _RRDB_X4_ANIME, _RRDB_X2]


def _build_rrdb_blocks(nn):
    """Real-ESRGAN 基础块（W24 规模拆分自 _build_torch_modules，零行为变更）。

    ResidualDenseBlock：5 层稠密卷积 + 0.2 残差缩放；RRDB：3×RDB 串联
    + 0.2 残差缩放（结构对齐 xinntao 上游 BSD-3-Clause 实现）。
    """
    import torch

    class ResidualDenseBlock(nn.Module):
        def __init__(self, num_feat: int = 64, num_grow_ch: int = 32):
            super().__init__()
            self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
            self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, num_feat: int, num_grow_ch: int):
            super().__init__()
            self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
            self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
            self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

        def forward(self, x):
            out = self.rdb1(x)
            out = self.rdb2(out)
            out = self.rdb3(out)
            return out * 0.2 + x

    return ResidualDenseBlock, RRDB


def _build_torch_modules():
    """惰性构建 torch 网络定义（模块级保持零 torch 依赖，R4 同款策略）。

    结构逐行对齐 xinntao/Real-ESRGAN realesrgan_arch.py（BSD-3-Clause）：
    - ResidualDenseBlock：5 层稠密卷积 + 0.2 残差缩放；
    - RRDB：3 × RDB 串联 + 0.2 残差缩放；
    - RRDBNet：x4 恒为"双 ×2 最近邻上采样卷积"，x2/x1 用 pixel_unshuffle
      预压缩空间换通道补偿（上游设计：骨干权重在多倍率间可迁移）；
    - SRVGGNetCompact：紧凑 VGG 式 + PixelShuffle（realesr-general-x4v3）。
    """
    import torch.nn as nn
    import torch.nn.functional as F

    ResidualDenseBlock, RRDB = _build_rrdb_blocks(nn)

    class RRDBNet(nn.Module):
        def __init__(self, num_in_ch=3, num_out_ch=3, scale=4,
                     num_feat=64, num_block=23, num_grow_ch=32):
            super().__init__()
            self.scale = scale
            if scale == 2:
                num_in_ch = num_in_ch * 4
            elif scale == 1:
                num_in_ch = num_in_ch * 16
            self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
            self.body = nn.Sequential(
                *[RRDB(num_feat, num_grow_ch) for _ in range(num_block)]
            )
            self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            feat = x
            if self.scale == 2:
                feat = F.pixel_unshuffle(feat, 2)
            elif self.scale == 1:
                feat = F.pixel_unshuffle(feat, 4)
            feat = self.conv_first(feat)
            body_feat = self.conv_body(self.body(feat))
            feat = feat + body_feat
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
            return self.conv_last(self.lrelu(self.conv_hr(feat)))

    class SRVGGNetCompact(nn.Module):
        def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64,
                     num_conv=32, upscale=4, act_type="prelu"):
            super().__init__()
            self.num_in_ch = num_in_ch
            self.num_out_ch = num_out_ch
            self.num_feat = num_feat
            self.num_conv = num_conv
            self.upscale = upscale
            self.act_type = act_type

            self.body = nn.ModuleList()
            self.body.append(nn.Conv2d(num_in_ch, num_feat, 3, 1, 1))
            if act_type == "relu":
                activation = nn.ReLU(inplace=True)
            elif act_type == "leakyrelu":
                activation = nn.LeakyReLU(negative_slope=0.1, inplace=True)
            elif act_type == "prelu":
                activation = nn.PReLU(num_parameters=num_feat)
            else:
                raise NotImplementedError(f"激活类型不支持: {act_type}")
            self.body.append(activation)
            for _ in range(num_conv):
                self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
                self.body.append(activation)
            self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
            self.upsampler = nn.PixelShuffle(upscale)

        def forward(self, x):
            out = x
            for layer in self.body:
                out = layer(out)
            return self.upsampler(out)

    return {"rrdbnet": RRDBNet, "srvgg": SRVGGNetCompact}


_TORCH_ARCH_CACHE: dict | None = None


def get_torch_archs() -> dict:
    """获取（并缓存）torch 架构类集合 {arch_name: nn.Module 类}。"""
    global _TORCH_ARCH_CACHE
    if _TORCH_ARCH_CACHE is None:
        _TORCH_ARCH_CACHE = _build_torch_modules()
    return _TORCH_ARCH_CACHE


class RealEsrganEngine(AbstractTaskEngine):
    """Real-ESRGAN 盲超分引擎（.pth 权重，GPU 优先 / CPU 回退）。

    load(weights.pth) → infer(lr_image) → HR 图像（extra["hr_image"]，BGR
    uint8）。大图自动分块（复用 inference.tiling_inferencer.compute_tiles
    网格 + 核心区裁剪粘贴，瓦片边界上下文外扩 tile_pad 像素消缝）。
    """

    def __init__(self) -> None:
        super().__init__(TaskType.SUPER)
        self._scale: int = 4
        self._arch_name: str = "rrdbnet"
        self._model_name: str = ""
        self._tile_size: int = 512
        self._tile_pad: int = 16
        self._torch_device: str = "cpu"

    # ---- 加载 ----

    def load(
        self,
        weights_path: str,
        device: str = "cuda",
        arch_overrides: dict | None = None,
        half: bool = False,
        tile_size: int = 512,
        tile_pad: int = 16,
    ) -> None:
        """加载 Real-ESRGAN 官方 .pth 权重。

        Args:
            weights_path: .pth/.pt 权重路径（官方发布或 state_dict 导出）。
            device: "cuda"（不可用时诚实回退 cpu 并留痕）/ "cpu"。
            arch_overrides: 架构参数覆盖（测试用小网络 / 非官方骨干），
                如 {"num_block": 1, "num_feat": 16, "num_grow_ch": 8}。
            half: CUDA 下转 fp16 推理（默认 False 保工业精度）。
            tile_size: 分块边长（大图防 OOM；<= 该值直推）。
            tile_pad: 瓦片上下文外扩像素（接缝抑制）。

        Raises:
            SupervisedEngineError: 文件不存在 / torch 缺失 / 权重与任何
                已知架构不匹配（不做插值放大的假超分，诚实回退）。
        """
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}（weights/ 不入仓；换机器请先"
                f"运行 scripts/download_realesrgan.py 拉取，或从离线供给目录拷贝）",
                task=self.task.value,
            )
        try:
            import torch  # noqa: F401
        except ImportError as exc:
            raise SupervisedEngineError(
                f"torch 未安装: {exc}", task=self.task.value
            ) from exc

        try:
            state = self._safe_torch_load(weights_path, map_location="cpu")
        except RuntimeError as exc:
            # 基类安全加载失败（非 torch.save 格式/损坏文件）→ 引擎错误契约
            raise SupervisedEngineError(
                f"权重文件无法安全加载: {exc}", task=self.task.value
            ) from exc
        state = self._unwrap_state_dict(state)

        candidates = [dict(c, **(arch_overrides or {})) for c in
                      arch_config_from_name(weights_path)]
        # 覆盖后仍允许 scale 显式指定（如 x2 权重改名为 x4 等）
        last_err = ""
        for cand in candidates:
            arch_name = cand["arch"]
            arch_cls = get_torch_archs()[arch_name]
            kwargs = {k: v for k, v in cand.items() if k != "arch"}
            if arch_name == "srvgg":
                kwargs.setdefault("upscale", kwargs.pop("scale", 4))
            try:
                model = arch_cls(**kwargs)
                model.load_state_dict(state, strict=True)
            except RuntimeError as exc:
                last_err = str(exc).splitlines()[0]
                continue
            self._model = model.eval()
            self._arch_name = arch_name
            self._scale = int(cand.get("scale", 4))
            self._model_name = os.path.splitext(os.path.basename(weights_path))[0]
            self._resolve_device(device, half=half)
            self._tile_size = max(int(tile_size), 64)
            self._tile_pad = max(int(tile_pad), 0)
            self._weights_path = weights_path
            logger.info(
                "Real-ESRGAN 权重已加载: %s（arch=%s scale=%dx device=%s tile=%d）",
                os.path.basename(weights_path), arch_name, self._scale,
                self._torch_device, self._tile_size,
            )
            return
        raise SupervisedEngineError(
            f"权重与已知 Real-ESRGAN 架构均不匹配（首个不匹配原因: {last_err}）；"
            f"请使用官方发布权重或标准 state_dict 导出",
            task=self.task.value,
        )

    def _resolve_device(self, device: str, half: bool) -> None:
        import torch

        requested = (device or "cuda").lower()
        if requested.startswith("cuda") and not torch.cuda.is_available():
            logger.warning("CUDA 不可用，Real-ESRGAN 回退 CPU 推理")
            requested = "cpu"
        self._torch_device = requested
        self._device = requested
        self._model = self._model.to(requested)
        if half and requested.startswith("cuda"):
            self._model = self._model.half()

    @staticmethod
    def _unwrap_state_dict(state: Any) -> Any:
        """兼容官方历史发布的包裹格式（params / params_ema / state_dict）。"""
        for key in ("params_ema", "params", "state_dict"):
            if isinstance(state, dict) and key in state and hasattr(state[key], "items"):
                return state[key]
        return state

    # ---- 推理 ----

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: list | None = None,
    ) -> DetectionResult:
        """超分推理：LR 图像（BGR）→ Real-ESRGAN → HR 图像。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)

        arr = self._to_numpy(image)
        if arr is None or not hasattr(arr, "shape") or arr.ndim < 2:
            raise SupervisedEngineError(
                "输入图像无效（读取失败或维度不足）", task=self.task.value
            )

        hr = self._infer_array(arr)
        return DetectionResult(
            task=TaskType.SUPER,
            score=1.0,
            labels=("super_resolved",),
            extra={
                "hr_image": hr,
                "backend": "realesrgan",
                "scale": self._scale,
                "model_name": self._model_name,
                "arch": self._arch_name,
            },
        )

    def _infer_array(self, arr: Any) -> Any:
        """整图入口：小图直推；大图分块（compute_tiles 网格 + 核心区粘贴）。"""
        import numpy as np

        h, w = arr.shape[:2]
        if h <= self._tile_size and w <= self._tile_size:
            return self._forward_tile(arr)

        scale = self._scale
        channels = arr.shape[2] if arr.ndim == 3 else 3
        out = np.zeros((h * scale, w * scale, channels), dtype=np.uint8)
        # overlap 取 2*tile_pad：瓦片各侧带 tile_pad 上下文，粘贴时两侧
        # 各退一半，接缝处两边都有完整感受野支撑
        pad = min(self._tile_pad, self._tile_size // 8)
        overlap = 2 * pad
        for x1, y1, x2, y2 in compute_tiles(h, w, self._tile_size, overlap):
            cx1 = x1 + pad if x1 > 0 else 0
            cy1 = y1 + pad if y1 > 0 else 0
            cx2 = x2 - pad if x2 < w else w
            cy2 = y2 - pad if y2 < h else h
            if cx2 <= cx1 or cy2 <= cy1:
                continue
            hr = self._forward_tile(arr[y1:y2, x1:x2])
            out[cy1 * scale: cy2 * scale, cx1 * scale: cx2 * scale] = hr[
                (cy1 - y1) * scale: (cy2 - y1) * scale,
                (cx1 - x1) * scale: (cx2 - x1) * scale,
            ]
        return out

    def _forward_tile(self, bgr: Any) -> Any:
        """单瓦片前向：BGR uint8 → RGB float tensor → 网络 → BGR uint8。"""
        import cv2
        import numpy as np
        import torch

        if bgr.ndim == 2:
            bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        tensor = torch.from_numpy(rgb).to(
            self._torch_device, dtype=self._model_dtype, non_blocking=False
        ).permute(2, 0, 1).unsqueeze(0).div_(255.0)
        with torch.no_grad():
            y = self._model(tensor)
        y = y.clamp_(0.0, 1.0)[0].permute(1, 2, 0).mul_(255.0).round_().byte()
        out_rgb = y.cpu().numpy()
        return cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)

    @property
    def _model_dtype(self) -> Any:
        import torch

        return torch.float16 if next(self._model.parameters()).dtype == torch.float16 \
            else torch.float32

    # ---- 元数据 ----

    @property
    def scale(self) -> int:
        """当前放大倍数。"""
        return self._scale

    @property
    def model_name(self) -> str:
        """当前模型名（权重文件主干）。"""
        return self._model_name

    @property
    def arch_name(self) -> str:
        """当前骨干架构名（rrdbnet / srvgg）。"""
        return self._arch_name

    @staticmethod
    def _to_numpy(image: Any) -> Any:
        """中文路径安全读图（BGR，与 super_cv2 契约一致）。"""
        import numpy as np

        if isinstance(image, str):
            from core.image_io import imread_unicode
            return imread_unicode(image)
        return np.asarray(image)


__all__ = ["RealEsrganEngine", "arch_config_from_name", "get_torch_archs"]
