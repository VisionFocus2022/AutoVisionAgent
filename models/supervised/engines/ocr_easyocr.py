"""OCR 引擎（easyocr，W32 可选任务）。

可选任务设计（W26 计划）：
- 模块级零 easyocr 依赖——@register_engine 注册零成本，缺库环境
  （含 lite 发行版）引擎照常注册、predict 任务项照常在列；
- load/infer 惰性导入 easyocr，缺库/缺离线权重诚实 raise
  SupervisedEngineError（带 scripts/fetch_ocr_weights.py 指引），
  不静默不返假数据；
- DetectionResult 映射：boxes=文本行 xyxy（quad 外接框）、
  labels=识别串、scores=逐行置信度（threshold 为置信度阈值）；
  proto 零改动（task 序列化为字符串 "ocr"）。

多语种：默认 ch_sim+en（craft_mlt_25k 检测 + zh_sim/latin 识别）。
"""
from __future__ import annotations

from typing import Any

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine
from models.supervised.device import resolve_device

_LANG_LIST = ("ch_sim", "en")


@register_engine(TaskType.OCR)
class OcrEasyocrEngine(AbstractTaskEngine):
    """easyocr 文字识别引擎（推理-only：训练页不列，W32）。"""

    def __init__(self) -> None:
        super().__init__(TaskType.OCR)

    def load(self, weights_path: str = "", device: str = "cpu") -> None:
        """加载 easyocr Reader。

        Args:
            weights_path: 离线权重目录（scripts/fetch_ocr_weights.py 供给；
                传入即禁用联网下载，缺权重诚实 raise）。空串 = easyocr
                默认 ~/.EasyOCR（首用下载，需联网）。
        """
        resolved = str(resolve_device(device))
        try:
            import easyocr
        except ImportError as exc:
            raise SupervisedEngineError(
                "easyocr 未安装——OCR 为可选任务：pip install easyocr==1.7.2"
                "（离线平台另需 scripts/fetch_ocr_weights.py 供给权重）",
                task=self.task.value,
            ) from exc

        offline = bool(weights_path)
        try:
            self._model = easyocr.Reader(
                list(_LANG_LIST),
                gpu=resolved.startswith("cuda"),
                model_storage_directory=weights_path or None,
                download_enabled=not offline,
            )
        except Exception as exc:  # noqa: BLE001  # Reader 初始化任何失败都诚实上抛
            raise SupervisedEngineError(
                f"easyocr 权重不可用: {exc}——离线平台请先运行 "
                "scripts/fetch_ocr_weights.py 下载 craft_mlt_25k/zh_sim 权重"
                "并以其输出目录作为模型路径加载",
                task=self.task.value,
            ) from exc
        self._weights_path = weights_path
        self._device = resolved

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: list | None = None,
    ) -> DetectionResult:
        """识别图中文本行（threshold 为逐行置信度阈值）。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)
        results = self._model.readtext(image, detail=1)
        boxes, texts, confs = [], [], []
        for quad, text, conf in results:
            if float(conf) < threshold:
                continue
            xs = [float(p[0]) for p in quad]
            ys = [float(p[1]) for p in quad]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
            texts.append(str(text))
            confs.append(float(conf))
        return DetectionResult(
            task=self.task,
            boxes=tuple(boxes),
            labels=tuple(texts),
            scores=tuple(confs),
            score=max(confs) if confs else 0.0,
        )


__all__ = ["OcrEasyocrEngine"]
