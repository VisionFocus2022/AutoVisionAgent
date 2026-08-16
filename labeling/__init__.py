"""labeling — 标注模块入口。

导出标注模式枚举、Shape 数据类和 LabelMe 读写函数。
"""
from __future__ import annotations

from labeling.base import (
    DEFAULT_COLOR,
    RGBA,
    AnnotationMode,
    ILabeler,
    Point,
    Shape,
)
from labeling.io_labelme import (
    labelme_to_shapes,
    load_labelme,
    load_labelme_shapes,
    save_labelme,
    shape_from_labelme,
    shape_to_labelme,
    shapes_to_labelme,
)

__all__ = [
    "Point",
    "RGBA",
    "DEFAULT_COLOR",
    "AnnotationMode",
    "Shape",
    "ILabeler",
    "save_labelme",
    "load_labelme",
    "load_labelme_shapes",
    "labelme_to_shapes",
    "shape_to_labelme",
    "shape_from_labelme",
    "shapes_to_labelme",
]
