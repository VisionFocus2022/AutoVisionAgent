"""标注模式工厂（FR-C1/C2/C3）。

按 AnnotationMode 解析到具体 ILabeler 实现。

手动 4 模式（POLYGON/RECTANGLE/BRUSH/KEYPOINT）：T-M1-09 实装。
AI 2 模式（AUTO/INTERACTIVE）：T-M2-03 SAM 适配器实装。

AUTO/INTERACTIVE 的 make_labeler 默认返回「无适配器」实例——
调用方需后续通过 set_adapter / set_detector / set_image 注入依赖。
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# 尝试导入标注基础设施（可能尚未实现）
try:
    from labeling.base import DEFAULT_COLOR, RGBA, AnnotationMode, ILabeler
except ImportError:
    _logger.warning("labeling.base 不可用，标注模式工厂将受限")
    # 提供最小桩定义防止崩溃
    from enum import Enum
    class AnnotationMode(Enum):
        POLYGON = "polygon"
        RECTANGLE = "rectangle"
        BRUSH = "brush"
        KEYPOINT = "keypoint"
        AUTO = "auto"
        INTERACTIVE = "interactive"
    RGBA = tuple[int, int, int, int]
    DEFAULT_COLOR = (52, 152, 219, 255)
    class ILabeler:  # type: ignore[no-redef]
        pass

# 尝试导入各标注器（缺失的模块会被跳过）
_LABELERS: dict = {}

for _name, _module_path in [
    ("AutoLabeler", "labeling.modes.auto"),
    ("BrushLabeler", "labeling.modes.brush"),
    ("InteractiveLabeler", "labeling.modes.interactive"),
    ("KeypointLabeler", "labeling.modes.keypoint"),
    ("PolygonLabeler", "labeling.modes.polygon"),
    ("RectangleLabeler", "labeling.modes.rectangle"),
    ("RegionSamLabeler", "labeling.modes.region_sam"),
    ("BrushSamLabeler", "labeling.modes.brush_sam"),
]:
    try:
        import importlib
        _mod = importlib.import_module(_module_path)
        _LABELERS[_name] = getattr(_mod, _name)
    except (ImportError, AttributeError):
        _logger.warning("标注器 %s 不可用，已跳过", _name)

# 导出可用标注器
globals().update(_LABELERS)

# 全模式工厂映射（动态构建，只包含已成功导入的标注器）
_ALL_FACTORIES = {}
_MANUAL_FACTORIES = {}

_MODE_LABELLER_MAP = {
    AnnotationMode.POLYGON: "PolygonLabeler",
    AnnotationMode.RECTANGLE: "RectangleLabeler",
    AnnotationMode.BRUSH: "BrushLabeler",
    AnnotationMode.KEYPOINT: "KeypointLabeler",
    AnnotationMode.AUTO: "AutoLabeler",
    AnnotationMode.INTERACTIVE: "InteractiveLabeler",
    AnnotationMode.REGION_SAM: "RegionSamLabeler",
    AnnotationMode.SAM_BRUSH: "BrushSamLabeler",
}

for _mode, _cls_name in _MODE_LABELLER_MAP.items():
    _cls = _LABELERS.get(_cls_name)
    if _cls is not None:
        _ALL_FACTORIES[_mode] = _cls
        if _mode in (AnnotationMode.POLYGON, AnnotationMode.RECTANGLE,
                     AnnotationMode.BRUSH, AnnotationMode.KEYPOINT):
            _MANUAL_FACTORIES[_mode] = _cls


def make_labeler(
    mode: AnnotationMode,
    label: str,
    color: RGBA = DEFAULT_COLOR,
    **options,
) -> ILabeler | None:
    """构造指定模式的标注器。

    Args:
        mode: 标注模式。
        label: 缺陷/类别名。
        color: 描边色 RGBA。
        **options: 模式专属参数（如 close_threshold / simplify_epsilon）。
            INTERACTIVE 模式：sam_adapter, image（可选，后续可注入）。
            AUTO 模式：detector, image（可选，后续可注入）。

    Returns:
        标注器实例；EDIT 模式返回 None（W55：编辑模式无标注器，鼠标
        事件由 controller 编辑分支接管，None 为合法值非构造失败）。

    Raises:
        ValueError: 未知模式。
    """
    if mode is AnnotationMode.EDIT:
        return None
    factory = _ALL_FACTORIES.get(mode)
    if factory is None:
        raise ValueError(f"未知标注模式: {mode}")
    return factory(label, color, **options)


__all__ = [
    "make_labeler",
] + list(_LABELERS.keys())
