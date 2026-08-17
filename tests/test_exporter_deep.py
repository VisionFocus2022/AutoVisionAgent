"""SupervisedExporter 深度测试（W10-T2 填洼）。

exporter/supervised_exporter.py 覆盖推进：
- export_onnx 真路径（torch.onnx.export 真 IO）+ 自动 input_shape 全任务分支
- 模型未加载 / 前向抛错 → ModelExportError 显式报错
- _validate_onnx 成功/失败；_try_simplify、fp16 量化缺依赖时的显式跳过分支
- int8 静态量化真路径 + 静态失败回退动态量化（故障注入 onnxruntime.quantize_static）
- export_tensorrt 未装 TensorRT 时的显式跳过；export_supervised_engine 便捷函数

依赖缺失纪律：onnxsim / onnxconverter_common / tensorrt 未装时只测
"显式跳过"分支（按实际环境探测决定），不伪造依赖可用假象；
export_tensorrt 的 TRT 真转换分支（141-182 行）需真实 tensorrt，不造假覆盖。
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys

import pytest

# 确保项目根在 sys.path
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

pytestmark = pytest.mark.unit

_LOGGER_NAME = "exporter.supervised_exporter"


# ============================== 测试替身 ============================== #

class _TinyNet:
    """微型真 torch 模块（conv → pool → fc），走真 torch.onnx.export。"""

    def __new__(cls):
        torch = pytest.importorskip("torch")
        import torch.nn as nn

        class _Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.conv = nn.Conv2d(3, 4, 1)
                self.pool = nn.AdaptiveAvgPool2d(1)
                self.fc = nn.Linear(4, 2)

            def forward(self, x):
                return self.fc(torch.flatten(self.pool(self.conv(x)), 1))

        net = _Net()
        net.eval()
        return net


class _BoomNet:
    """forward 抛错的真 torch 模块（触发导出失败包装路径）。"""

    def __new__(cls):
        torch = pytest.importorskip("torch")
        import torch.nn as nn

        class _Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.conv = nn.Conv2d(3, 4, 1)

            def forward(self, x):
                raise RuntimeError("boom in forward")

        net = _Net()
        net.eval()
        return net


class _StubEngine:
    """最小引擎替身：task + _model 即满足 export 路径。"""

    def __init__(self, task, model):
        self.task = task
        self._model = model


def _make_engine(task_value: str, model) -> "_StubEngine":
    from core.interfaces_supervised import TaskType
    return _StubEngine(TaskType(task_value), model)


@pytest.fixture
def spy_randn(monkeypatch):
    """记录 torch.randn 收到的 shape，并透传真实现（导出仍为真路径）。"""
    torch = pytest.importorskip("torch")
    real_randn = torch.randn
    shapes: list = []

    def _spy(*args, **kwargs):
        shapes.append(args[0] if args else kwargs.get("size"))
        return real_randn(*args, **kwargs)

    monkeypatch.setattr(torch, "randn", _spy)
    return shapes


# ============================== export_onnx ============================== #

class TestExportOnnx:
    """export_onnx 成败路径（真 torch.onnx.export）。"""

    def test_fp32_cls_auto_shape_real_export(self, tmp_path, spy_randn):
        """cls 任务自动选 (1,3,224,224)，真导出 + 动态轴落盘。"""
        from exporter.supervised_exporter import SupervisedExporter

        out = tmp_path / "cls_model.onnx"
        ret = SupervisedExporter().export_onnx(
            _make_engine("cls", _TinyNet()), str(out)
        )
        assert str(out) == ret
        assert out.exists() and out.stat().st_size > 0
        # 自动形状选择：cls → 224
        assert spy_randn == [(1, 3, 224, 224)]
        # 结构断言：onnx 可加载、输入名与动态 batch 轴真实生效
        onnx = pytest.importorskip("onnx")
        model = onnx.load(str(out))
        onnx.checker.check_model(model)
        assert model.graph.input[0].name == "input"
        batch_dim = model.graph.input[0].type.tensor_type.shape.dim[0]
        assert batch_dim.dim_param == "batch_size"

    @pytest.mark.parametrize(
        "task_value,expected",
        [
            ("det", (1, 3, 640, 640)),
            ("pseg", (1, 3, 640, 640)),
            ("pose", (1, 3, 640, 640)),
            ("sseg", (1, 3, 512, 512)),
            ("super", (1, 3, 256, 256)),
            ("sgan", (1, 3, 640, 640)),  # else 兜底分支
        ],
    )
    def test_auto_shape_per_task(self, tmp_path, spy_randn, task_value, expected):
        """各任务的自动 input_shape 选择逻辑（真导出验证不抛错）。"""
        from exporter.supervised_exporter import SupervisedExporter

        out = tmp_path / f"{task_value}_model.onnx"
        SupervisedExporter().export_onnx(_make_engine(task_value, _TinyNet()), str(out))
        assert spy_randn == [expected]
        assert out.exists() and out.stat().st_size > 0

    def test_explicit_shape_wins(self, tmp_path, spy_randn):
        """显式 input_shape 时不走自动选择。"""
        from exporter.supervised_exporter import SupervisedExporter

        out = tmp_path / "explicit.onnx"
        SupervisedExporter().export_onnx(
            _make_engine("cls", _TinyNet()), str(out), input_shape=(1, 3, 64, 64)
        )
        assert spy_randn == [(1, 3, 64, 64)]  # 未被 224 覆盖
        assert out.exists()

    def test_engine_without_model_raises(self, tmp_path):
        """引擎未加载模型 → ModelExportError。"""
        from core.exceptions import ModelExportError
        from exporter.supervised_exporter import SupervisedExporter

        engine = _make_engine("cls", None)
        with pytest.raises(ModelExportError, match="引擎未加载模型"):
            SupervisedExporter().export_onnx(engine, str(tmp_path / "x.onnx"))

    def test_forward_failure_wrapped_as_export_error(self, tmp_path):
        """前向抛错被包装为 ModelExportError，details 携带路径。"""
        from core.exceptions import ModelExportError
        from exporter.supervised_exporter import SupervisedExporter

        out = tmp_path / "boom.onnx"
        with pytest.raises(ModelExportError, match="ONNX 导出失败") as exc:
            SupervisedExporter().export_onnx(
                _make_engine("cls", _BoomNet()), str(out), input_shape=(1, 3, 32, 32)
            )
        assert exc.value.details.get("path") == str(out)
        assert not out.exists()  # 失败时不落盘

    def test_plain_callable_without_parameters(self, tmp_path):
        """无 parameters 属性的可调用 → device 走 "cpu" 兜底；torch 端要求
        nn.Module（内部调用 model.modules()），失败被包装为 ModelExportError。"""
        from core.exceptions import ModelExportError
        from exporter.supervised_exporter import SupervisedExporter

        class _PlainCallable:
            def eval(self):
                return self

            def __call__(self, x):  # 恒等映射
                return x

        out = tmp_path / "plain.onnx"
        with pytest.raises(ModelExportError, match="ONNX 导出失败"):
            SupervisedExporter().export_onnx(
                _StubEngine(type("T", (), {"value": "cls"})(), _PlainCallable()),
                str(out),
                input_shape=(1, 3, 32, 32),
            )
        assert not out.exists()


# ============================== 内部步骤：校验/简化/量化 ============================== #

class TestValidateAndSimplify:
    """_validate_onnx / _try_simplify 分支。"""

    def test_validate_ok_logs_ir_version(self, tmp_path, caplog):
        """合法 ONNX → 验证通过日志（真 onnx.checker）。"""
        onnx = pytest.importorskip("onnx")
        torch = pytest.importorskip("torch")
        from exporter.supervised_exporter import SupervisedExporter

        p = tmp_path / "ok.onnx"
        torch.onnx.export(_TinyNet(), torch.randn(1, 3, 32, 32), str(p))
        caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
        SupervisedExporter()._validate_onnx(p)
        assert "ONNX 模型验证通过" in caplog.text
        assert f"IR version={onnx.load(str(p)).ir_version}" in caplog.text

    def test_validate_corrupt_file_warns_not_raises(self, tmp_path, caplog):
        """损坏文件 → 警告但不抛（模型可能仍可用语义）。"""
        pytest.importorskip("onnx")
        from exporter.supervised_exporter import SupervisedExporter

        p = tmp_path / "bad.onnx"
        p.write_bytes(b"not an onnx model at all")
        caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)
        SupervisedExporter()._validate_onnx(p)  # 不得抛出
        assert "ONNX 模型验证失败" in caplog.text

    def test_simplify_onnxsim_missing_skips(self, tmp_path, caplog):
        """onnxsim 未安装 → 显式跳过简化（debug 日志），原文件保留。"""
        pytest.importorskip("onnx")
        torch = pytest.importorskip("torch")
        if importlib.util.find_spec("onnxsim"):
            pytest.skip("onnxsim 已安装，ImportError 分支不可达")
        from exporter.supervised_exporter import SupervisedExporter

        p = tmp_path / "raw.onnx"
        torch.onnx.export(_TinyNet(), torch.randn(1, 3, 32, 32), str(p))
        size_before = p.stat().st_size
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
        SupervisedExporter()._try_simplify(p)
        assert "onnxsim 未安装" in caplog.text
        assert p.stat().st_size == size_before


class TestQuantize:
    """_try_quantize 分支（fp16 缺依赖 / int8 真量化与回退）。"""

    def test_fp16_missing_converter_skips_via_public_api(self, tmp_path, caplog):
        """precision=fp16 且 onnxconverter_common 未装 → 导出成功、量化显式跳过。"""
        if importlib.util.find_spec("onnxconverter_common"):
            pytest.skip("onnxconverter_common 已安装，ImportError 分支不可达")
        from exporter.supervised_exporter import SupervisedExporter

        out = tmp_path / "fp16.onnx"
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
        ret = SupervisedExporter().export_onnx(
            _make_engine("cls", _TinyNet()), str(out),
            input_shape=(1, 3, 32, 32), precision="fp16",
        )
        assert ret == str(out) and out.exists()  # 导出本身不受量化缺依赖影响
        assert "量化依赖未安装，跳过 fp16 量化" in caplog.text

    def test_int8_static_quantize_real(self, tmp_path, caplog):
        """precision=int8 → 静态量化真路径产出 .int8.onnx 兄弟文件。"""
        pytest.importorskip("onnxruntime")
        from exporter.supervised_exporter import SupervisedExporter

        out = tmp_path / "int8.onnx"
        caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
        SupervisedExporter().export_onnx(
            _make_engine("cls", _TinyNet()), str(out),
            input_shape=(1, 3, 32, 32), precision="int8",
        )
        int8_path = out.with_suffix(".int8.onnx")
        assert int8_path.exists() and int8_path.stat().st_size > 0
        # 本环境实测静态量化成功；若静态不可用则必须走动态回退
        assert "静态量化成功" in caplog.text or "动态量化成功" in caplog.text

    def test_int8_static_failure_falls_back_dynamic(self, tmp_path, caplog, monkeypatch):
        """静态量化抛非 ImportError → 回退动态量化（真 quantize_dynamic 落盘）。"""
        ort_quant = pytest.importorskip("onnxruntime.quantization")
        torch = pytest.importorskip("torch")
        from exporter.supervised_exporter import SupervisedExporter

        def _boom_static(*args, **kwargs):
            raise RuntimeError("static quantization boom")

        monkeypatch.setattr(ort_quant, "quantize_static", _boom_static)
        p = tmp_path / "fb.onnx"
        torch.onnx.export(_TinyNet(), torch.randn(1, 3, 32, 32), str(p))
        caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
        SupervisedExporter()._try_quantize(p, "int8", (1, 3, 32, 32))
        int8_path = p.with_suffix(".int8.onnx")
        assert int8_path.exists() and int8_path.stat().st_size > 0
        assert "INT8 动态量化成功（静态不可用）" in caplog.text


# ============================== export_tensorrt ============================== #

class TestExportTensorRT:
    """export_tensorrt：TensorRT 未安装的显式降级路径。"""

    def test_trt_missing_returns_onnx_path(self, tmp_path, caplog):
        """TRT 未装 → 警告并原样返回 onnx 路径，不产出 engine 文件。"""
        if importlib.util.find_spec("tensorrt"):
            pytest.skip("tensorrt 已安装，ImportError 分支不可达")
        torch = pytest.importorskip("torch")
        from exporter.supervised_exporter import SupervisedExporter

        onnx_path = tmp_path / "m.onnx"
        torch.onnx.export(_TinyNet(), torch.randn(1, 3, 32, 32), str(onnx_path))
        engine_path = tmp_path / "m.engine"
        caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)
        ret = SupervisedExporter().export_tensorrt(
            str(onnx_path), str(engine_path), precision="fp16"
        )
        assert ret == str(onnx_path)  # 显式降级：返回输入路径
        assert not engine_path.exists()
        assert "TensorRT 未安装" in caplog.text


# ============================== export_supervised_engine ============================== #

class TestExportSupervisedEngine:
    """便捷函数 export_supervised_engine。"""

    def test_onnx_only(self, tmp_path):
        """formats=("onnx",) → 按任务命名导出单个 onnx。"""
        from exporter.supervised_exporter import export_supervised_engine

        results = export_supervised_engine(
            _make_engine("det", _TinyNet()), str(tmp_path), formats=("onnx",)
        )
        assert set(results) == {"onnx"}
        assert results["onnx"].endswith(os.path.join(tmp_path.name, "det_model.onnx")) \
            or results["onnx"].endswith("det_model.onnx")
        assert os.path.exists(results["onnx"])

    def test_trt_format_returns_onnx_path_when_missing(self, tmp_path):
        """formats=("onnx","trt") + TRT 未装 → results['trt'] == onnx 路径。"""
        if importlib.util.find_spec("tensorrt"):
            pytest.skip("tensorrt 已安装，降级分支不可达")
        from exporter.supervised_exporter import export_supervised_engine

        results = export_supervised_engine(
            _make_engine("cls", _TinyNet()), str(tmp_path), formats=("onnx", "trt")
        )
        assert set(results) == {"onnx", "trt"}
        assert results["trt"] == results["onnx"]  # 降级返回输入路径
        assert not os.path.exists(str(tmp_path / "cls_model.engine"))

    def test_taskless_engine_exports_as_unknown(self, tmp_path, spy_randn):
        """无 task 属性的引擎 → "unknown_model.onnx" + 默认 640 形状（曾 AttributeError）。"""
        from exporter.supervised_exporter import export_supervised_engine

        class _TasklessEngine:  # 仅有 _model，无 task（便捷函数 hasattr 分支）
            def __init__(self, model):
                self._model = model

        results = export_supervised_engine(
            _TasklessEngine(_TinyNet()), str(tmp_path), formats=("onnx",)
        )
        assert set(results) == {"onnx"}
        assert results["onnx"].endswith("unknown_model.onnx")
        assert os.path.exists(results["onnx"])
        assert spy_randn == [(1, 3, 640, 640)]  # "" → else 兜底形状
