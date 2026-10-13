"""有监督引擎导出整合（FR-E）— T-AVA-14

将有监督任务引擎对接到 inference/onnx_exporter 和 TensorRT 加速链路。
支持将底层 nn.Module 导出为 ONNX + 量化 + TRT（W18：export_onnx 为显式
参数形态 model/task_value/path——引擎字段提取仅保留在 export_supervised_engine
便捷门面，调用方无需再造引擎桩）。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

from core.exceptions import ModelExportError
from core.interfaces_supervised import ISupervisedTaskEngine

logger = logging.getLogger(__name__)


class _DummyCalibReader:
    """随机数据校准 reader（X8：仅 calib_images=None 的占位回退）。"""

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


class _FileCalibReader:
    """X8（2026-10-06 三轮审查）：真实样本校准 reader。

    PIL 读图 → RGB → resize 到输入形状 → NCHW float32 [0,1]。坏图跳过
    并告警；全部坏图时 get_next 首调返回 None 之外的路径由 quantize_static
    抛错复用既有动态回退（显式 RuntimeError 更可诊断）。
    """

    def __init__(self, image_paths: Sequence[str], input_shape: tuple):
        import numpy as np
        from PIL import Image

        c, h, w = (input_shape[1], input_shape[2], input_shape[3]) \
            if len(input_shape) == 4 else (3, 640, 640)
        self._data = []
        self._idx = 0
        loaded = 0
        for p in image_paths:
            try:
                with Image.open(p) as im:
                    im = im.convert("RGB").resize((w, h), Image.BILINEAR)
                    arr = np.asarray(im, dtype=np.float32) / 255.0
                # HWC → NCHW（补 batch 维，与 _DummyCalibReader 的完整
                # input_shape 对齐；缺维会导致 quantize_static 喂数失败
                # 而静默回退动态量化，真实校准样本实际不生效）
                self._data.append({"input": arr.transpose(2, 0, 1)[None, ...]})
                loaded += 1
            except (OSError, ValueError):
                logger.warning("X8: 校准图跳过（损坏/不可读）: %s", p, exc_info=True)
        if loaded == 0:
            raise RuntimeError(
                f"X8: 全部 {len(image_paths)} 张校准图均不可读——回退动态量化"
            )
        logger.info("X8: 校准样本就绪 %d/%d 张", loaded, len(image_paths))

    def get_next(self):
        if self._idx >= len(self._data):
            return None
        d = self._data[self._idx]
        self._idx += 1
        return d


class SupervisedExporter:
    """有监督引擎导出器。

    流程：
    1. 接收显式参数（nn.Module + task_value）——W18 起不再吃 engine 对象
       （旧形态内取 .task.value 与 ._model，迫使调用方造引擎桩）
    2. 调用 inference/onnx_exporter 导出 ONNX
    3. 可选：TensorRT 转换
    """

    def __init__(self, opset: int = 14, simplify: bool = True) -> None:
        self._opset = opset
        self._simplify = simplify

    def export_onnx(
        self,
        model,
        task_value: str,
        output_path: str,
        input_shape: tuple | None = None,
        precision: str = "fp32",
        calib_images: Sequence[str] | None = None,
    ) -> str:
        """
        导出有监督模型为 ONNX（W18：显式参数形态）。

        Args:
            model: 已加载权重的底层 nn.Module（完整模型对象）。
            task_value: 任务值（cls/det/pseg/pose/sseg/super...，
                用于 input_shape 未显式给出时自动选择）。
            output_path: 输出 .onnx 路径。
            input_shape: 输入张量形状（None 时按 task_value 自动选择）。
            precision: fp32/fp16/int8。
            calib_images: X8（2026-10-06 三轮审查）——int8 静态量化校准
                图路径序列。None 保持随机数据校准并显式 WARNING（精度
                风险）；传入时真读图喂 quantize_static（推荐 ≥32 张
                真实产线样本）。GUI 侧接数据集目录选择另行排期。

        Returns:
            导出的 ONNX 文件路径。
        """
        if model is None:
            raise ModelExportError("模型未加载", details={})

        model.eval()
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # W24 规模拆分（2026-10-06）：input_shape 自动选择 + torch.onnx.export
        # + X14 原子写抽至 _export_base_onnx，本方法保留编排。
        # R4-F3（2026-10-07 四轮审查）：_export_base_onnx 返回 (path, 有效
        # shape) 元组——此前 auto 选择的 shape 是其局部变量，量化侧仍收
        # None 兜底 640：cls(224)/sseg(512) 模型的 int8 校准分辨率错配，
        # 激活统计建立在错误分布上（量化精度静默劣化）。
        out_path, input_shape = self._export_base_onnx(
            model, task_value, out_path, input_shape
        )

        # 验证导出的 ONNX 模型结构完整性
        self._validate_onnx(out_path)

        # 简化
        if self._simplify:
            self._try_simplify(out_path)

        # 量化
        # X7（2026-10-06 三轮审查）：int8 产物写在 .int8.onnx，此前仍返回
        # 原 fp32 路径——调用方（GUI/审计）报告的文件与实际产物不符。
        # 现以 _try_quantize 返回的实际产物路径为准。
        if precision in ("fp16", "int8"):
            quantized = self._try_quantize(
                out_path, precision, input_shape, calib_images=calib_images
            )
            if quantized is not None:
                return str(quantized)

        return str(out_path)

    def _export_base_onnx(
        self,
        model,
        task_value: str,
        out_path: Path,
        input_shape: tuple | None,
    ) -> tuple[Path, tuple]:
        """W24 拆分：shape 选择 + torch.onnx.export + X14 原子写。

        X14（2026-10-06 三轮审查）：直写最终路径在导出中途失败会残留
        半截 .onnx——先写 .tmp（同目录保同卷原子性），校验通过后
        os.replace；失败 finally 清理 tmp，目标文件零污染。
        R4-F3（2026-10-07 四轮审查）：返回 (out_path, 有效 input_shape)
        ——auto 选择的 shape 必须回传给量化链路（校准分辨率一致性）。
        """
        import torch

        if input_shape is None:
            if task_value == "cls":
                input_shape = (1, 3, 224, 224)
            elif task_value in ("det", "pseg", "pose"):
                input_shape = (1, 3, 640, 640)
            elif task_value == "sseg":
                input_shape = (1, 3, 512, 512)
            elif task_value == "super":
                input_shape = (1, 3, 256, 256)
            else:
                input_shape = (1, 3, 640, 640)
            logger.info("自动选择 input_shape=%s (task=%s)", input_shape, task_value)

        try:
            device = next(model.parameters()).device
        except (StopIteration, AttributeError):
            # X14 加固：无参数模块（纯函数式/占位）与 Duck-typed 对象回退 cpu
            device = "cpu"
        dummy = torch.randn(input_shape, device=device)

        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        try:
            torch.onnx.export(
                model,
                dummy,
                str(tmp_path),
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
            os.replace(tmp_path, out_path)  # X14：原子落位
            logger.info("ONNX 导出成功: %s", out_path)
        except Exception as exc:
            raise ModelExportError(
                f"ONNX 导出失败: {exc}", details={"path": str(out_path)}
            ) from exc
        finally:
            # X14：失败/异常路径清理 tmp（成功路径已被 replace 消费）
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    logger.warning("临时文件清理失败: %s", tmp_path, exc_info=True)
        return out_path, input_shape  # R4-F3：有效 shape（auto 已解析）回传

    def export_tensorrt(
        self,
        onnx_path: str,
        output_path: str,
        precision: str = "fp16",
        max_batch_size: int = 8,
        workspace_size_mb: int = 4096,
        input_shape: tuple | None = None,
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
                      input_shape: tuple | None = None,
                      calib_images: Sequence[str] | None = None) -> Path | None:
        """X7：返回实际量化产物路径（None=未量化/依赖缺失跳过）。

        int8 写 .int8.onnx；fp16 原地覆盖返回原路径。
        X8（2026-10-06 三轮审查）：calib_images 注入真实校准样本——
        None 保持随机校准 + WARNING（精度风险显式化）；传入走
        _FileCalibReader 真读图（PIL→RGB→resize→NCHW float32），
        坏图跳过、全坏抛 RuntimeError 复用既有动态回退路径。
        """
        try:
            if precision == "fp16":
                import onnx
                from onnxconverter_common import float16

                model = onnx.load(str(path))
                model_fp16 = float16.convert_float_to_float16(model)
                onnx.save(model_fp16, str(path))
                logger.info("FP16 量化成功")
                return path
            elif precision == "int8":
                # 优先使用静态量化（精度更高），回退到动态量化
                try:
                    from onnxruntime.quantization import (
                        CalibrationMethod,
                        QuantType,
                        quantize_static,
                    )
                    int8_path = path.with_suffix(".int8.onnx")
                    # 使用实际模型输入形状生成校准数据
                    calib_shape = input_shape if input_shape else (1, 3, 640, 640)

                    if calib_images:
                        reader = _FileCalibReader(calib_images, calib_shape)
                    else:
                        # X8：随机校准占位 + 显式精度风险告警（此前静默）
                        logger.warning(
                            "X8: 未提供校准样本（calib_images=None），int8 "
                            "使用随机数据校准——量化后精度可能显著劣化，"
                            "上产线前必须用真实样本复验！"
                        )
                        reader = _DummyCalibReader(calib_shape)

                    quantize_static(
                        str(path), str(int8_path),
                        reader,
                        quant_format=None,
                        weight_type=QuantType.QInt8,
                        calibrate_method=CalibrationMethod.MinMax,
                    )
                    logger.info(
                        "INT8 静态量化成功（校准源：%s）",
                        f"{len(calib_images)} 张真实样本" if calib_images else "随机数据",
                    )
                    return int8_path
                except Exception:
                    # R4-F2（2026-10-07 四轮审查）：回退原因必须留痕——此前
                    # 静默吞掉，用户显式提供的校准图全坏被无声换成动态量化
                    # （精度更差）而无从排障。
                    logger.exception(
                        "INT8 静态量化失败，回退动态量化%s",
                        "（用户提供的校准样本未生效！）" if calib_images else "",
                    )
                    from onnxruntime.quantization import QuantType, quantize_dynamic
                    int8_path = path.with_suffix(".int8.onnx")
                    quantize_dynamic(str(path), str(int8_path),
                                     weight_type=QuantType.QUInt8)
                    logger.info("INT8 动态量化成功（静态不可用）")
                    return int8_path
        except ImportError:
            logger.debug("量化依赖未安装，跳过 %s 量化", precision)
            return None


def export_supervised_engine(
    engine: ISupervisedTaskEngine,
    output_dir: str,
    formats: tuple = ("onnx",),
    precision: str = "fp32",
) -> dict[str, str]:
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
    results: dict[str, str] = {}

    if "onnx" in formats:
        onnx_path = Path(output_dir) / f"{task}_model.onnx"
        # W18：export_onnx 显式参数形态——此处提取引擎字段后转调
        results["onnx"] = exporter.export_onnx(
            getattr(engine, "_model", None), task, str(onnx_path), precision=precision
        )

    if "trt" in formats and "onnx" in results:
        trt_path = Path(output_dir) / f"{task}_model.engine"
        results["trt"] = exporter.export_tensorrt(
            results["onnx"], str(trt_path), precision=precision
        )

    return results


__all__ = ["SupervisedExporter", "export_supervised_engine"]
