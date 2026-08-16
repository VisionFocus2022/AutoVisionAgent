"""有监督任务引擎实现集（M2 完整版：9 任务全注册）。

每个引擎模块在导入时通过 @register_engine 自注册到默认注册表。
调用 ``register_all_engines()`` 触发全部引擎注册（惰性导入重依赖）。
"""
from __future__ import annotations


def register_all_engines() -> None:
    """惰性导入并注册全部 9 种有监督引擎。

    缺失的引擎模块（如 det_yolo/seg_yolo/abdet_anomalib）会被跳过并记录警告，
    不影响其他已实现引擎的注册。
    """
    import logging
    _logger = logging.getLogger(__name__)

    _engine_modules = [
        # M1：det / seg / abdet
        "abdet_anomalib",
        "det_yolo",
        "seg_yolo",
        # M2：cls / pose / pseg / sseg / sgan / super
        "cls_torchvision",
        "pose_yolo",
        "pseg_yolo",
        "sseg_mmseg",
        "sgan_mmedit",
        "super_mmedit",
    ]
    for _mod in _engine_modules:
        try:
            __import__(f"models.supervised.engines.{_mod}")
        except ImportError:
            _logger.warning("引擎模块 %s 不可用，已跳过", _mod)


__all__ = ["register_all_engines"]
