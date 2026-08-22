"""有监督任务引擎实现集（W2 移植后：9/9 全实装；W32 增 OCR 可选件 = 10）。

det/seg/abdet 与 sgan_blend/super_cv2 于 W2 自兄弟树（era-4 "Option A 真化"产物）移植；
sgan/super 已弃 mmedit 桩：sgan=seamlessClone Poisson 融合，super=cv2.dnn_superres，
缺库/缺权重时诚实 raise（不返假数据）。
每个引擎模块在导入时通过 @register_engine 自注册到默认注册表。
调用 ``register_all_engines()`` 触发全部引擎注册（惰性导入重依赖）。
"""
from __future__ import annotations


def register_all_engines() -> None:
    """惰性导入并注册全部 10 种有监督引擎（OCR 为可选件）。

    缺失的引擎模块会被跳过并记录警告，不影响其他已实现引擎的注册。
    """
    import logging
    _logger = logging.getLogger(__name__)

    _engine_modules = [
        # M1：det / seg / abdet（W2 移植）
        "abdet_anomalib",
        "det_yolo",
        "seg_yolo",
        # M2：cls / pose / pseg / sseg / sgan / super
        "cls_torchvision",
        "pose_yolo",
        "pseg_yolo",
        "sseg_smp",
        "sgan_blend",
        "super_cv2",
        # W32：OCR 可选任务（模块级零 easyocr 依赖，惰性导入）
        "ocr_easyocr",
    ]
    for _mod in _engine_modules:
        try:
            __import__(f"models.supervised.engines.{_mod}")
        except ImportError:
            _logger.warning("引擎模块 %s 不可用，已跳过", _mod)


__all__ = ["register_all_engines"]
