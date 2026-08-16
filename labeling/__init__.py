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
from labeling.io_labelme import save_labelme, load_labelme, load_labelme_shapes

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
]
