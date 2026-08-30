"""W19（v3 第三波 FR-3.1）引擎 device 护栏测试。

PRD docs/prd-wave19-v3-wave3.md FR-3.1：
- ``resolve_device(device)``：device 为 ``"cuda"``（大小写不敏感）且
  ``torch.cuda.is_available()`` 为 False → 回退 ``"cpu"`` 并 logger.warning 留痕；
  cpu / None / 其他（如 ``"cuda:0"`` 非精确 cuda 串）一律原样返回，不做二次猜测。
- 所有以 torch 为后端且实有 device 形参的引擎 ``load()`` 顶部接入归一：
  det / seg（_yolo_seg_base 基类）/ pose / pseg / cls / sseg / abdet 共 7 类
  （cv2 系 super_cv2 与非 torch 的 sgan_blend 不在本护栏范围，见簇 deviations）。

离线策略（沿用 tests/test_engines_family_deep.py 的 I/O 边界替身注入惯例）：
- ultralytics / anomalib / segmentation_models_pytorch 一律 sys.modules 注入
  假模块（不 import 真库——本文件只测 device 归一，不测模型构造）；
- cls_torchvision 的 ``_safe_torch_load`` 换替身返回微型假模型，真 transforms
  流水线保留（无模型依赖，快速确定）；
- abdet 替身记录 ``map_location``，证明归一发生在 checkpoint 加载之前。
"""
from __future__ import annotations

import logging
import os
import sys
import types
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("torch")
pytest.importorskip("torchvision")

import torch  # noqa: E402

from models.supervised.engines.abdet_anomalib import AbdetAnomalibEngine  # noqa: E402
from models.supervised.engines.cls_torchvision import ClsTorchvisionEngine  # noqa: E402
from models.supervised.engines.det_yolo import DetYoloEngine  # noqa: E402
from models.supervised.engines.pose_yolo import PoseYoloEngine  # noqa: E402
from models.supervised.engines.pseg_yolo import PsegYoloEngine  # noqa: E402
from models.supervised.engines.seg_yolo import SegYoloEngine  # noqa: E402
from models.supervised.engines.sseg_smp import SsegSmpEngine  # noqa: E402

# ============================== 替身 ============================== #


class _FakeTorchModel:
    """微型 torch 模型替身：eval()/to()/load_state_dict 契约即可。"""

    def __init__(self) -> None:
        self.moved_to: Any = None

    def eval(self) -> _FakeTorchModel:
        return self

    def to(self, device: Any) -> _FakeTorchModel:
        self.moved_to = device
        return self

    def load_state_dict(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeYolo:
    """ultralytics YOLO 构造替身（沿用 test_engines_family_deep 惯例）。"""

    def __init__(self, weights_path: str) -> None:
        self.weights_path = weights_path


class _FakePatchcore:
    """anomalib Patchcore 替身：记录 map_location 供断言归一发生时序。"""

    last_map_location: Any = None

    @classmethod
    def load_from_checkpoint(cls, path: str, map_location: str = "cpu") -> _FakeTorchModel:
        cls.last_map_location = map_location
        return _FakeTorchModel()


def _stub_heavy_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """把引擎 load 依赖的重后端全部换成假模块（本文件只测 device 归一）。"""
    fake_yolo_mod = types.ModuleType("ultralytics")
    fake_yolo_mod.YOLO = _FakeYolo  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ultralytics", fake_yolo_mod)

    # W19：假 smp（DeepLabV3Plus 构造替身，避免真建 resnet50）
    fake_smp = types.ModuleType("segmentation_models_pytorch")

    def _fake_model_cls(**kwargs: Any) -> _FakeTorchModel:
        return _FakeTorchModel()

    fake_smp.DeepLabV3Plus = _fake_model_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "segmentation_models_pytorch", fake_smp)

    # W19：假 anomalib.models.Patchcore（记录 map_location）
    fake_anomalib = types.ModuleType("anomalib")
    fake_anomalib_models = types.ModuleType("anomalib.models")
    fake_anomalib_models.Patchcore = _FakePatchcore  # type: ignore[attr-defined]
    fake_anomalib.models = fake_anomalib_models  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anomalib", fake_anomalib)
    monkeypatch.setitem(sys.modules, "anomalib.models", fake_anomalib_models)

    # I/O 边界替身：cls 需要假模型对象；sseg 需要空 state dict
    monkeypatch.setattr(
        ClsTorchvisionEngine,
        "_safe_torch_load",
        staticmethod(lambda path, map_location="cpu": _FakeTorchModel()),
    )
    monkeypatch.setattr(
        SsegSmpEngine,
        "_safe_torch_load",
        staticmethod(lambda path, map_location="cpu": {}),
    )


# W19（FR-3.1）：torch 后端且实有 device 形参的引擎清单（7 类）
TORCH_ENGINES = [
    DetYoloEngine,
    SegYoloEngine,
    PoseYoloEngine,
    PsegYoloEngine,
    ClsTorchvisionEngine,
    SsegSmpEngine,
    AbdetAnomalibEngine,
]


# ============================== resolve_device 单元 ============================== #


@pytest.fixture
def resolve():
    """懒导入被测函数：RED 阶段模块缺失时只影响本组用例，引擎用例独立失败。"""
    from models.supervised.device import resolve_device

    return resolve_device


def test_resolve_device_cuda_available_passthrough(monkeypatch, resolve):
    """cuda 可用时 cuda 请求必须原样通过（不得过度归一）。"""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve("cuda") == "cuda"
    assert resolve("CUDA") == "CUDA"  # 大小写不敏感仅用于识别，非回退原样透传


def test_resolve_device_cuda_unavailable_falls_back_cpu(monkeypatch, caplog, resolve):
    """cuda 不可用 → 回退 cpu 且必须告警留痕（不静默换设备）。"""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with caplog.at_level(logging.WARNING, logger="models.supervised.device"):
        assert resolve("cuda") == "cpu"
    assert "CUDA" in caplog.text
    # 大小写不敏感的 cuda 请求同样回退
    assert resolve("CUDA") == "cpu"


def test_resolve_device_non_cuda_passthrough(monkeypatch, resolve):
    """cpu/None/其他/非精确 cuda 串一律原样返回（含 cuda 不可用场景）。"""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve("cpu") == "cpu"
    assert resolve("CPU") == "CPU"
    assert resolve(None) is None
    assert resolve("cuda:0") == "cuda:0"
    assert resolve("mps") == "mps"
    assert resolve("") == ""


# ============================== 引擎 load 接入 ============================== #


@pytest.mark.parametrize("engine_cls", TORCH_ENGINES, ids=lambda c: c.__name__)
def test_engine_load_cuda_unavailable_falls_back_to_cpu(
    monkeypatch, tmp_path, engine_cls
):
    """W19 FR-3.1：cuda 不可用时 load(device="cuda") 内部必须归一为 cpu。"""
    _stub_heavy_backends(monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"fake-weights")

    engine = engine_cls()
    engine.load(str(weights), device="cuda")
    assert engine._device == "cpu"


def test_engine_load_cuda_available_keeps_cuda(monkeypatch, tmp_path):
    """cuda 可用时不得一刀切回退（det 抽查，防过度归一回归）。"""
    _stub_heavy_backends(monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"fake-weights")

    engine = DetYoloEngine()
    engine.load(str(weights), device="cuda")
    assert engine._device == "cuda"


def test_abdet_resolves_device_before_checkpoint_load(monkeypatch, tmp_path):
    """abdet 归一必须发生在 Patchcore.load_from_checkpoint(map_location=) 之前。"""
    _stub_heavy_backends(monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    ckpt = tmp_path / "model.ckpt"
    ckpt.write_bytes(b"fake-ckpt")

    engine = AbdetAnomalibEngine()
    engine.load(str(ckpt), device="cuda")
    assert _FakePatchcore.last_map_location == "cpu"
    assert engine._device == "cpu"


def test_cls_moves_model_to_resolved_cpu_device(monkeypatch, tmp_path):
    """cls 的 model.to() 也必须拿到归一后的 device（cpu），而非透传 cuda。"""
    _stub_heavy_backends(monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"fake-weights")

    engine = ClsTorchvisionEngine()
    engine.load(str(weights), device="cuda")
    assert engine._device == "cpu"
    assert engine._model.moved_to == "cpu"
