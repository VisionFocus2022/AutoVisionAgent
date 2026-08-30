"""W19（v3 第三波 FR-1.1）：det 引擎 GPU 推理显存峰值基准。

口径：yolov8n 合成权重（torch.manual_seed 固定）+ ``device="cuda:0"`` 钉死；
warmup 2 轮（权重上卡 + cudnn/上下文初始化不计入峰值窗口）后
``torch.cuda.reset_peak_memory_stats()`` → 10 轮 infer →
``torch.cuda.max_memory_allocated()``（MiB）。

GPU 不可用 → ``pytest.skip`` 诚实标注（FR-1.1：不伪造；AC-1.3 只落档）。
"""
from __future__ import annotations

import _common
import numpy as np
import pytest

_ROUNDS = 10
_WARMUP = 2
_THRESHOLD = 0.0  # 与 bench_infer 同口径：全候选满载后处理路径
_IMG = np.random.RandomState(42).randint(0, 256, (320, 320, 3), dtype=np.uint8)


def test_vram_peak_det_gpu():
    """det GPU 推理显存峰值（max_memory_allocated，稳态窗口）。"""
    import torch

    if not torch.cuda.is_available():
        pytest.skip(
            "W19（FR-1.1）：本机 CUDA 不可用，显存峰值基准诚实跳过（AC-1.3 不伪造）"
        )
    from ultralytics import YOLO

    from models.supervised.engines.det_yolo import DetYoloEngine

    torch.manual_seed(_common.TORCH_SEED)
    model = YOLO("yolov8n.yaml")
    model.overrides["device"] = "cuda:0"
    eng = DetYoloEngine()
    eng._model = model
    eng._device = "cuda:0"

    detected = len(eng.infer(_IMG, threshold=_THRESHOLD).boxes or ())
    for _ in range(_WARMUP - 1):
        eng.infer(_IMG, threshold=_THRESHOLD)
    torch.cuda.synchronize()

    base_mib = torch.cuda.memory_allocated() / 2**20
    torch.cuda.reset_peak_memory_stats()
    for _ in range(_ROUNDS):
        eng.infer(_IMG, threshold=_THRESHOLD)
    torch.cuda.synchronize()
    peak_mib = torch.cuda.max_memory_allocated() / 2**20

    # 单值指标：仅 max 列有意义，分布列留空由 summarize 渲染为 —
    stats = {
        "n": _ROUNDS, "p50": None, "p95": None, "p99": None,
        "mean": None, "min": None, "max": round(peak_mib, 1),
    }
    _common.append_record(
        _common.make_record(
            "vram", "vram_det_yolov8n_gpu", "vram_peak_mib", stats,
            threshold=_THRESHOLD, warmup=_WARMUP, device="cuda:0",
            detected=detected, torch_seed=_common.TORCH_SEED,
            baseline_allocated_mib=round(base_mib, 1),
            gpu=torch.cuda.get_device_name(0),
        )
    )
    # 结构自检（相对性质）：峰值 ≥ 稳态基线，且为正数
    assert peak_mib >= base_mib
    assert peak_mib > 0
