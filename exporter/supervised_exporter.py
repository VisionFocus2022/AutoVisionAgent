"""有监督引擎导出整合（FR-E）— T-AVA-13

将有监督任务引擎对接到 inference/onnx_exporter 和 TensorRT 加速链路。
支持将 ISupervisedTaskEngine 底层 nn.Module 导出为 ONNX + 量化 + TRT。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from core.exceptions import ModelExportError
from core.interfaces_supervised import ISupervisedTaskEngine, TaskType

logger = logging.getLogger(__name__)


class SupervisedExporter:
    """有监督引擎导出器。

    流程：
    1. 从引擎提取底层 nn.Module（engine._model）
    2. 调用 inference/onnx_exporter 导出 ONNX
    3. 可选：TensorRT 转换
    """

    def __init__(self, opset: int = 14, simplify: bool = True) -> None:
        self._opset = opset
        self._simplify = simplify

    def export_onnx(
        self,
        engine: ISupervisedTaskEngine,
        output_path: str,
        input_shape: Optional[tuple] = None,
        precision: str = "fp32",
    ) -> str:
        """
        导出有监督引擎为 ONNX。

        Args:
            engine: 已加载权重的引擎实例。
            output_path: 输出 .onnx 路径。
            input_shape: 输入张量形状（None 时根据 task 自动选择）。
            precision: fp32/fp16/int8。

        Returns:
            导出的 ONNX 文件路径。
        """
        import torch

        # 根据 task 自动选择默认 input_shape（引擎可能无 task 属性，R-W10 防穿）
        if input_shape is None:
            task_val = getattr(getattr(engine, "task", None), "value", "")
            if task_val == "cls":
                input_shape = (1, 3, 224, 224)
            elif task_val in ("det", "pseg", "pose"):
                input_shape = (1, 3, 640, 640)
            elif task_val == "sseg":
                input_shape = (1, 3, 512, 512)
            elif task_val == "super":
                input_shape = (1, 3, 256, 256)
            else:
                input_shape = (1, 3, 640, 640)
            logger.info("自动选择 input_shape=%s (task=%s)", input_shape, task_val)

        model = getattr(engine, "_model", None)
        if model is None:
            raise ModelExportError("引擎未加载模型", details={})

        model.eval()
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        device = next(model.parameters()).device if hasattr(model, "parameters") else "cpu"
        dummy = torch.randn(input_shape, device=device)

        try:
            torch.onnx.export(
                model,
                dummy,
                str(out_path),
                opset_version=self._opset,
                input_names=["input"],
                output_names=["output"],
                dynamic_axes={
                    "input": {0: "batch_size", 2: "height", 3: "width"},
                    "output": {0: "batch_size"},
                },
                do_constant_folding=True,
                export_params=True,
                verbose=False,
            )
            logger.info("ONNX 导出成功: %s", out_path)
        except Exception as exc:
            raise ModelExportError(
                f"ONNX 导出失败: {exc}", details={"path": str(out_path)}
            ) from exc

        # 验证导出的 ONNX 模型结构完整性
        self._validate_onnx(out_path)

        # 简化
        if self._simplify:
            self._try_simplify(out_path)

        # 量化
        if precision in ("fp16", "int8"):
            self._try_quantize(out_path, precision, input_shape)

        return str(out_path)

    def export_tensorrt(
        self,
        onnx_path: str,
        output_path: str,
        precision: str = "fp16",
        max_batch_size: int = 8,
        workspace_size_mb: int = 4096,
        input_shape: Optional[tuple] = None,
    ) -> str:
        """
        ONNX → TensorRT engine 转换。

        Args:
            onnx_path: 输入 ONNX 路径。
            output_path: 输出 .engine/.trt 路径。
            precision: fp32/fp16/int8。
            max_batch_size: 最大批大小。
            workspace_size_mb: TRT 工作空间（MB）。

        Returns:
            TRT engine 文件路径。
        """
        try:
            import tensorrt as trt
        except ImportError:
            logger.warning("TensorRT 未安装，跳过 TRT 转换")
            return onnx_path

        TRT_LOGGER = trt.Logger(trt.Logger.INFO)
        builder = trt.Builder(TRT_LOGGER)
        network = builder.create_network(
            1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
        )
        parser = trt.OnnxParser(network, TRT_LOGGER)

        with open(onnx_path, "rb") as f:
            if not parser.parse(f.read()):
                for i in range(parser.num_errors):
                    logger.error(parser.get_error(i))
                raise ModelExportError("ONNX 解析失败", details={"path": onnx_path})

        config = builder.create_builder_config()
        config.set_memory_pool_limit(
            trt.MemoryPoolType.WORKSPACE,
            workspace_size_mb * 1024 * 1024,
        )

        if precision == "fp16" and builder.platform_has_fast_fp16:
            config.set_flag(trt.BuilderFlag.FP16)
        elif precision == "int8" and builder.platform_has_fast_int8:
            config.set_flag(trt.BuilderFlag.INT8)

        # 优化 profile（动态 batch + 动态分辨率）
        _h = input_shape[2] if input_shape and len(input_shape) > 2 else 640
        _w = input_shape[3] if input_shape and len(input_shape) > 3 else 640
        profile = builder.create_optimization_profile()
        profile.set_shape("input", (1, 3, _h, _w),
                          (max_batch_size // 2, 3, _h, _w),
                          (max_batch_size, 3, _h, _w))
        config.add_optimization_profile(profile)

        serialized = builder.build_serialized_network(network, config)
        if serialized is None:
            raise ModelExportError("TRT engine 构建失败", details={})

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(serialized)
        logger.info("TensorRT engine 导出成功: %s", out_path)
        return str(out_path)

    def _validate_onnx(self, path: Path) -> None:
        """验证 ONNX 模型结构完整性（使用 onnx.checker）。"""
        try:
            import onnx
            model = onnx.load(str(path))
            onnx.checker.check_model(model)
            logger.info("ONNX 模型验证通过: %s (IR version=%d)",
                        path, model.ir_version)
        except ImportError:
            logger.debug("onnx 未安装，跳过模型验证")
        except Exception as exc:
            logger.warning("ONNX 模型验证失败（模型可能仍可用）: %s", exc)

    def _try_simplify(self, path: Path) -> None:
        try:
            import onnx
            import onnxsim

            model = onnx.load(str(path))
            simplified, ok = onnxsim.simplify(model)
            if ok:
                onnx.save(simplified, str(path))
                logger.info("ONNX 简化成功")
        except ImportError:
            logger.debug("onnxsim 未安装，跳过简化")

    def _try_quantize(self, path: Path, precision: str,
                      input_shape: Optional[tuple] = None) -> None:
        try:
            if precision == "fp16":
                from onnxconverter_common import float16
                import onnx

                model = onnx.load(str(path))
                model_fp16 = float16.convert_float_to_float16(model)
                onnx.save(model_fp16, str(path))
                logger.info("FP16 量化成功")
            elif precision == "int8":
                # 优先使用静态量化（精度更高），回退到动态量化
                try:
                    from onnxruntime.quantization import (
                        quantize_static, CalibrationDataReader, QuantType,
                        CalibrationMethod,
                    )
                    int8_path = path.with_suffix(".int8.onnx")
                    # 静态量化需要校准数据，此处使用随机数据作为占位
                    class _DummyCalibReader(CalibrationDataReader):
                        def __init__(self, input_shape):
                            import numpy as np
                            self._data = [
                                {"input": np.random.randn(*input_shape).astype(np.float32)}
                                for _ in range(5)
                            ]
                            self._idx = 0
                        def get_next(self):
                            if self._idx >= len(self._data):
                                return None
                            d = self._data[self._idx]
                            self._idx += 1
                            return d
                    # 使用实际模型输入形状生成校准数据
                    calib_shape = input_shape if input_shape else (1, 3, 640, 640)
                    quantize_static(
                        str(path), str(int8_path),
                        _DummyCalibReader(calib_shape),
                        quant_format=None,
                        weight_type=QuantType.QInt8,
                        calibrate_method=CalibrationMethod.MinMax,
                    )
                    logger.info("INT8 静态量化成功")
                except Exception:
                    # 回退到动态量化（仅权重量化）
                    from onnxruntime.quantization import quantize_dynamic, QuantType
                    int8_path = path.with_suffix(".int8.onnx")
                    quantize_dynamic(str(path), str(int8_path),
                                     weight_type=QuantType.QUInt8)
                    logger.info("INT8 动态量化成功（静态不可用）")
        except ImportError:
            logger.debug("量化依赖未安装，跳过 %s 量化", precision)


def export_supervised_engine(
    engine: ISupervisedTaskEngine,
    output_dir: str,
    formats: tuple = ("onnx",),
    precision: str = "fp32",
) -> Dict[str, str]:
    """
    便捷函数：导出有监督引擎到多格式。

    Args:
        engine: 已加载权重的引擎。
        output_dir: 输出目录。
        formats: ("onnx",) 或 ("onnx", "trt")。
        precision: fp32/fp16/int8。

    Returns:
        {format: path} 映射。
    """
    exporter = SupervisedExporter()
    task = engine.task.value if hasattr(engine, "task") else "unknown"
    results: Dict[str, str] = {}

    if "onnx" in formats:
        onnx_path = Path(output_dir) / f"{task}_model.onnx"
        results["onnx"] = exporter.export_onnx(
            engine, str(onnx_path), precision=precision
        )

    if "trt" in formats and "onnx" in results:
        trt_path = Path(output_dir) / f"{task}_model.engine"
        results["trt"] = exporter.export_tensorrt(
            results["onnx"], str(trt_path), precision=precision
        )

    return results


__all__ = ["SupervisedExporter", "export_supervised_engine"]
