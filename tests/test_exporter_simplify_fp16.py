"""exporter onnxsim/fp16 门控路径补测（W14-C4 ④，依赖门控解锁）。

前置：onnxsim 0.7.3 + onnxconverter-common 1.16.0 已装（W14 实测），
解锁 _try_simplify 真简化路径（:202-206）与 fp16 量化路径（:213-220）。
onnxsim 缺库跳过分支（:207-208）经 sys.modules 注入覆盖。
TRT 路径（:141-182）依赖 TensorRT，本机无卡不伪造——留缺口不测。
"""
from __future__ import annotations

import logging
import sys

import pytest

torch = pytest.importorskip("torch")
onnx = pytest.importorskip("onnx")
onnxsim = pytest.importorskip("onnxsim")  # 0.7.3（W14-C4 装入）

from exporter.supervised_exporter import SupervisedExporter  # noqa: E402


def _make_model():
    """微型导出模型：单层 Conv2d（W18 起显式参数直传，无需引擎包装）。"""
    m = torch.nn.Conv2d(3, 2, kernel_size=3, bias=True)
    m.eval()
    return m


@pytest.fixture
def exporter():
    return SupervisedExporter(opset=14, simplify=True)


def _export(exporter, tmp_path, precision="fp32"):
    path = tmp_path / "m.onnx"
    out = exporter.export_onnx(_make_model(), "cls", str(path),
                               input_shape=(1, 3, 16, 16), precision=precision)
    assert out == str(path) and path.exists()
    return path


# ============================== onnxsim 简化路径 ============================== #
@pytest.mark.unit
def test_simplify_real_onnxsim_rewrites_model(exporter, tmp_path, caplog):
    """真 onnxsim.simplify：ok=True 时回写文件 + info 日志（:202-206）。"""
    with caplog.at_level(logging.INFO, logger="exporter.supervised_exporter"):
        path = _export(exporter, tmp_path)
    assert any("ONNX 简化成功" in r.getMessage() for r in caplog.records)
    model = onnx.load(str(path))  # 简化后仍是合法 ONNX
    onnx.checker.check_model(model)
    assert model.graph.input[0].name == "input"


@pytest.mark.unit
def test_simplify_missing_onnxsim_skips_and_keeps_file(
    tmp_path, monkeypatch, caplog
):
    """onnxsim 不可导入 → debug 跳过，文件字节不动（:207-208）。"""
    exp = SupervisedExporter(opset=14, simplify=False)
    path = _export(exp, tmp_path)
    before = path.read_bytes()

    monkeypatch.setitem(sys.modules, "onnxsim", None)
    with caplog.at_level(logging.DEBUG, logger="exporter.supervised_exporter"):
        exp._try_simplify(path)
    assert any("onnxsim 未安装" in r.getMessage() for r in caplog.records)
    assert path.read_bytes() == before  # 未简化：文件保持原样


# ============================== fp16 量化路径 ============================== #
@pytest.mark.unit
def test_quantize_fp16_converts_weights(exporter, tmp_path, caplog):
    """precision=fp16 → onnxconverter_common.float16 真转换 + 回写
    （:213-220）：卷积权重 initializer 应为 FLOAT16。"""
    with caplog.at_level(logging.INFO, logger="exporter.supervised_exporter"):
        path = _export(exporter, tmp_path, precision="fp16")
    assert any("FP16 量化成功" in r.getMessage() for r in caplog.records)

    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    dtypes = {init.data_type for init in model.graph.initializer}
    assert onnx.TensorProto.FLOAT16 in dtypes  # 权重确已转半精度


# ============================== 依赖缺失告警分支 ============================== #
@pytest.mark.unit
def test_validate_onnx_missing_onnx_skips(tmp_path, monkeypatch, caplog):
    """onnx 不可导入 → debug 跳过验证（:193）。"""
    path = tmp_path / "m.onnx"
    _export(SupervisedExporter(simplify=False), tmp_path)
    monkeypatch.setitem(sys.modules, "onnx", None)
    with caplog.at_level(logging.DEBUG, logger="exporter.supervised_exporter"):
        SupervisedExporter()._validate_onnx(path)  # 不得抛
    assert any("onnx 未安装" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_quantize_missing_converter_skips(tmp_path, monkeypatch, caplog):
    """onnxconverter_common 不可导入 → 量化整体跳过、文件不动（:261-262）。"""
    path = _export(SupervisedExporter(simplify=False), tmp_path)
    before = path.read_bytes()
    monkeypatch.setitem(sys.modules, "onnxconverter_common", None)
    with caplog.at_level(logging.DEBUG, logger="exporter.supervised_exporter"):
        SupervisedExporter()._try_quantize(path, "fp16", (1, 3, 16, 16))
    assert any("量化依赖未安装" in r.getMessage() for r in caplog.records)
    assert path.read_bytes() == before
