"""W19（v3 第三波 FR-1.1）：det/cls/seg 三任务引擎 CPU 合成权重推理时延基准。

口径（与 docs/prd-wave19-v3-wave3.md FR-1.1 对齐）：
- 合成权重：det/seg 用 ultralytics 架构 yaml 直建随机权重（不联网下载，同
  tests/test_engine_det_real.py:95 / test_engines_family_deep.py:802 口径），
  构建前 ``torch.manual_seed(0)``（个别种子 0 检出 flaky，见 _common 注释）；
  cls 用 torchvision resnet18(weights=None)（不联网），经真 load() 路径
  （I/O 边界 mock 注入网络对象，合法口径同 tests/test_engines_family_deep.py
  :356-366），transform 流水线为 load() 真实构建。
- 计时：每引擎 warmup 2 + 30 轮 perf_counter 逐轮（毫秒），自算 p50/p95/p99
  ——pytest-benchmark stats 无 p99（FR-1.1），AC-1.3 只落档不断言绝对值。
- 设备：本机有 RTX 3060，ultralytics 默认自动选 GPU，故必须显式
  ``model.overrides["device"] = "cpu"`` 钉死 CPU，否则时延口径失真。
- 结果追加写入 .benchmarks/wave19-raw.json，由 benchmarks/summarize.py 落档。
"""
from __future__ import annotations

from typing import Any

import _common
import numpy as np
import pytest

# 确定性输入图（RandomState 固定；尺寸/种子对齐仓库既有引擎测试口径）
_DET_IMG = np.random.RandomState(42).randint(0, 256, (320, 320, 3), dtype=np.uint8)
_SEG_IMG = np.random.RandomState(7).randint(0, 256, (128, 128, 3), dtype=np.uint8)
_CLS_IMG = np.random.RandomState(3).randint(0, 256, (320, 320, 3), dtype=np.uint8)

# conf=0.0：随机权重置信度普遍低于工业阈值（本机实测 0.25 下 0 检出），
# 0.0 强制全候选过阈值，NMS+解析路径满载且确定性（family_deep 真模型同口径）
_THRESHOLD = 0.0
_WARMUP = 2
_ROUNDS = 30


def _build_det_engine_cpu() -> Any:
    """det 引擎：yolov8n.yaml 随机权重 + CPU 钉死。"""
    import torch
    from ultralytics import YOLO

    from models.supervised.engines.det_yolo import DetYoloEngine

    torch.manual_seed(_common.TORCH_SEED)
    model = YOLO("yolov8n.yaml")
    model.overrides["device"] = "cpu"
    eng = DetYoloEngine()
    eng._model = model
    eng._device = "cpu"
    return eng


def _build_seg_engine_cpu() -> Any:
    """seg 引擎：yolov8n-seg.yaml 随机权重 + CPU 钉死。"""
    import torch
    from ultralytics import YOLO

    from models.supervised.engines.seg_yolo import SegYoloEngine

    torch.manual_seed(_common.TORCH_SEED)
    model = YOLO("yolov8n-seg.yaml")
    model.overrides["device"] = "cpu"
    eng = SegYoloEngine()
    eng._model = model
    eng._device = "cpu"
    return eng


def _build_cls_engine_cpu(tmp_path: Any) -> Any:
    """cls 引擎：resnet18 随机权重，经真 load()（I/O 边界注入网络对象）。"""
    from unittest.mock import patch

    import torch
    from torchvision import models

    from models.supervised.engines.cls_torchvision import ClsTorchvisionEngine

    torch.manual_seed(_common.TORCH_SEED)
    net = models.resnet18(weights=None)
    # I/O 边界 mock（合法口径同 tests/test_engines_family_deep.py:356-366）：
    # 本机无 .pt 资产，且 state_dict 落盘经安全加载会退回 dict（.eval() 失败），
    # 故按仓库测试同法注入网络对象，load() 其余真路径（eval + transform 构建）原样执行
    fake_pt = tmp_path / "bench_cls_synthetic.pth"
    fake_pt.write_bytes(b"synthetic")
    with patch.object(
        ClsTorchvisionEngine,
        "_safe_torch_load",
        new=staticmethod(lambda p, map_location="cpu": net),
    ):
        eng = ClsTorchvisionEngine()
        eng.load(str(fake_pt), device="cpu")
    return eng


def _record_latency(case: str, eng: Any, img: np.ndarray, detected: int) -> None:
    """统一计时 + 记录 + 结构自检（非绝对值断言，AC-1.3）。"""
    samples = _common.time_rounds(
        lambda: eng.infer(img, threshold=_THRESHOLD), _WARMUP, _ROUNDS
    )
    stats = _common.summarize_samples(samples)
    _common.append_record(
        _common.make_record(
            "infer", case, "latency_ms", stats,
            threshold=_THRESHOLD, warmup=_WARMUP, device="cpu",
            detected=detected, torch_seed=_common.TORCH_SEED,
        )
    )
    # 结构自检：样本数齐全且分位数单调（相对性质，非绝对性能断言）
    assert stats["n"] == _ROUNDS
    assert stats["p50"] <= stats["p95"] <= stats["p99"]


@pytest.mark.integration
def test_infer_latency_det_cpu():
    """det（yolov8n 合成权重）CPU 推理时延 p50/p95/p99。"""
    eng = _build_det_engine_cpu()
    warm = eng.infer(_DET_IMG, threshold=_THRESHOLD)
    _record_latency("infer_det_yolov8n_cpu", eng, _DET_IMG, len(warm.boxes or ()))


@pytest.mark.integration
def test_infer_latency_seg_cpu():
    """seg（yolov8n-seg 合成权重）CPU 推理时延 p50/p95/p99。"""
    eng = _build_seg_engine_cpu()
    warm = eng.infer(_SEG_IMG, threshold=_THRESHOLD)
    _record_latency("infer_seg_yolov8n_cpu", eng, _SEG_IMG, len(warm.boxes or ()))


@pytest.mark.integration
def test_infer_latency_cls_cpu(tmp_path):
    """cls（resnet18 合成权重）CPU 推理时延 p50/p95/p99。"""
    eng = _build_cls_engine_cpu(tmp_path)
    warm = eng.infer(_CLS_IMG, threshold=_THRESHOLD)
    _record_latency("infer_cls_resnet18_cpu", eng, _CLS_IMG, len(warm.labels or ()))
