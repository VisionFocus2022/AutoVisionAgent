"""LabelMe JSON 读写（FR-C5）。

Shape ↔ LabelMe 标注字典互转，格式对齐 ``evaluation/labelme_loader.py``（后者消费
shape_type=="polygon" 的 points）。本模块：

- POLYGON → shape_type "polygon"；RECTANGLE/OPERATION → "rectangle"；
  CUT_LINE → "linestrip"（labelme 原生折线形态，跨工具互操作——外部
  工具写的 linestrip 读回 CUT_LINE；W56 对标 SKolpha cut_line_label/
  operation_label）。
- 为保留原始模式身份以支持精确往返，在每个 shape 字典附 ``"mode"`` 自定义键；
  既有 loader 忽略未知键，故向后兼容（零回归）。
- 不内嵌 imageData（保持文件轻量；图像经 imagePath 引用，与 evaluation loader 一致）。
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from core.exceptions import AnnotationIOError, InvalidShapeError
from labeling.base import (
    DEFAULT_COLOR,
    AnnotationMode,
    Shape,
)

# LabelMe 标注文件版本（写出处）
LABELME_VERSION = "5.4.3"

# Shape.mode → LabelMe shape_type
_MODE_TO_SHAPE_TYPE: dict[AnnotationMode, str] = {
    AnnotationMode.POLYGON: "polygon",
    AnnotationMode.RECTANGLE: "rectangle",
    AnnotationMode.CUT_LINE: "linestrip",       # W56：切割线（labelme 原生形态）
    AnnotationMode.OPERATION: "rectangle",      # W56：操作区域（矩形形态）
}

# LabelMe shape_type → Shape.mode（无 "mode" 自定义键时的推断回退）
# （"point" 形态随关键点模式移除——旧 point 数据走未知形态路径，诚实不支持）
_SHAPE_TYPE_TO_MODE: dict[str, AnnotationMode] = {
    "polygon": AnnotationMode.POLYGON,
    "rectangle": AnnotationMode.RECTANGLE,
    "linestrip": AnnotationMode.CUT_LINE,       # W56：外部 linestrip 读为切割线
}


def shape_to_labelme(shape: Shape) -> dict[str, Any]:
    """单个 Shape → LabelMe shape 字典。"""
    if not shape.points:
        raise InvalidShapeError("形状无点", mode=shape.mode.value)
    shape_type = _MODE_TO_SHAPE_TYPE.get(shape.mode)
    if shape_type is None:
        raise InvalidShapeError(
            f"模式 {shape.mode.value} 暂不支持 LabelMe 导出", mode=shape.mode.value
        )
    # 矩形/操作标注只需两个对角点；多边形/切割线按原样
    _TWO_POINT_MODES = (AnnotationMode.RECTANGLE, AnnotationMode.OPERATION)
    pts = tuple(shape.points[:2]) if shape.mode in _TWO_POINT_MODES else shape.points
    return {
        "label": shape.label,
        "points": [[float(x), float(y)] for x, y in pts],
        "group_id": shape.group_id,
        "shape_type": shape_type,
        # 自定义键：保留原始模式以支持精确往返（既有 loader 忽略）
        "mode": shape.mode.value,
        "flags": {k: v for k, v in shape.flags} if shape.flags else {},
    }


def shape_from_labelme(data: dict[str, Any]) -> Shape:
    """LabelMe shape 字典 → Shape。优先用 "mode" 自定义键，否则按 shape_type 推断。"""
    raw_mode = data.get("mode")
    if raw_mode and raw_mode in {m.value for m in AnnotationMode}:
        mode = AnnotationMode(raw_mode)
    else:
        shape_type = data.get("shape_type", "polygon")
        mode = _SHAPE_TYPE_TO_MODE.get(shape_type, AnnotationMode.POLYGON)

    raw_points = data.get("points") or []
    points: tuple = tuple((float(x), float(y)) for x, y in raw_points)
    if not points:
        raise InvalidShapeError("LabelMe shape 无 points", mode=mode.value)

    flags = tuple(
        (str(k), bool(v)) for k, v in (data.get("flags") or {}).items()
    )
    group_id = data.get("group_id")
    return Shape(
        mode=mode,
        points=points,
        label=str(data.get("label", "")),
        color=DEFAULT_COLOR,  # 颜色不持久化于 labelme 标准字段，读回用默认
        group_id=int(group_id) if group_id is not None else None,
        flags=flags,
    )


def labelme_to_shapes(doc: dict[str, Any]) -> list[Shape]:
    """完整 LabelMe 文档字典 → Shape 列表。（W1: 自 era-2 树移植）"""
    out: list[Shape] = []
    for item in doc.get("shapes") or []:
        if not isinstance(item, dict):
            continue
        out.append(shape_from_labelme(item))
    return out


def shapes_to_labelme(
    shapes: Sequence[Shape],
    image_path: str,
    image_height: int,
    image_width: int,
    image_data: str | None = None,
    channels: int | None = None,
    image_path_list: list[str] | None = None,
    mark: str = "",
) -> dict[str, Any]:
    """多个 Shape + 图像元信息 → 完整 LabelMe 文档字典。

    工业扩展字段（可选，向后兼容）：
    - channels: 图像通道数（1=灰度，3=RGB）。工业相机常用单通道。
    - image_path_list: 多图序列路径列表（批处理标注）。
    - mark: 标注备注/审核意见。
    """
    doc = {
        "version": LABELME_VERSION,
        "flags": {},
        "shapes": [shape_to_labelme(s) for s in shapes],
        "imagePath": image_path,
        "imageData": image_data,
        "imageHeight": int(image_height),
        "imageWidth": int(image_width),
    }
    # 工业扩展字段（仅在提供时写入，保持与标准 LabelMe 的向后兼容）
    if channels is not None:
        doc["channels"] = int(channels)
    if image_path_list:
        doc["image_path_list"] = list(image_path_list)
    if mark:
        doc["mark"] = mark
    return doc


def save_labelme(
    path: str | Path,
    shapes: Sequence[Shape],
    image_path: str,
    image_height: int,
    image_width: int,
    image_data: str | None = None,
    channels: int | None = None,
    image_path_list: list[str] | None = None,
    mark: str = "",
) -> None:
    """把标注写入 LabelMe JSON 文件。

    工业扩展字段（可选）：channels / image_path_list / mark。

    Raises:
        AnnotationIOError: 落盘失败（目录不存在/权限/JSON 序列化）。
    """
    doc = shapes_to_labelme(
        shapes, image_path, image_height, image_width, image_data,
        channels=channels, image_path_list=image_path_list, mark=mark,
    )
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as exc:
        raise AnnotationIOError(
            f"写入 LabelMe 失败: {p}", path=str(p)
        ) from exc


def load_labelme(path: str | Path) -> dict[str, Any]:
    """读取 LabelMe JSON 文件为原始字典。

    Raises:
        AnnotationIOError: 文件不存在或 JSON 解析失败。
    """
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnnotationIOError(
            f"LabelMe 文件不存在: {p}", path=str(p)
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AnnotationIOError(
            f"LabelMe 解析失败: {p}", path=str(p)
        ) from exc


def load_labelme_shapes(path: str | Path) -> list[Shape]:
    """读取 LabelMe JSON 文件并返回 Shape 列表。"""
    return labelme_to_shapes(load_labelme(path))


__all__ = [
    "LABELME_VERSION",
    "labelme_to_shapes",
    "load_labelme",
    "load_labelme_shapes",
    "save_labelme",
    "shape_from_labelme",
    "shape_to_labelme",
    "shapes_to_labelme",
]
