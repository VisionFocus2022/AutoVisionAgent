"""LabelMe JSON 读写（FR-C5）。

Shape ↔ LabelMe 标注字典互转，格式对齐 ``evaluation/labelme_loader.py``（后者消费
shape_type=="polygon" 的 points）。本模块：

- POLYGON/BRUSH → shape_type "polygon"；RECTANGLE → "rectangle"；KEYPOINT → "point"。
- 为保留画笔（brush）身份以支持精确往返，在每个 shape 字典附 ``"mode"`` 自定义键；
  既有 loader 忽略未知键，故向后兼容（零回归）。
- 不内嵌 imageData（保持文件轻量；图像经 imagePath 引用，与 evaluation loader 一致）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from core.exceptions import AnnotationIOError, InvalidShapeError
from labeling.base import (
    DEFAULT_COLOR,
    AnnotationMode,
    Shape,
)

# LabelMe 标注文件版本（写出处）
LABELME_VERSION = "5.4.3"

# Shape.mode → LabelMe shape_type
_MODE_TO_SHAPE_TYPE: Dict[AnnotationMode, str] = {
    AnnotationMode.POLYGON: "polygon",
    AnnotationMode.BRUSH: "polygon",   # 画笔落盘为多边形（与既有 loader 兼容）
    AnnotationMode.RECTANGLE: "rectangle",
    AnnotationMode.KEYPOINT: "point",
}

# LabelMe shape_type → Shape.mode（无 "mode" 自定义键时的推断回退）
_SHAPE_TYPE_TO_MODE: Dict[str, AnnotationMode] = {
    "polygon": AnnotationMode.POLYGON,
    "rectangle": AnnotationMode.RECTANGLE,
    "point": AnnotationMode.KEYPOINT,
}


def shape_to_labelme(shape: Shape) -> Dict[str, Any]:
    """单个 Shape → LabelMe shape 字典。"""
    if not shape.points:
        raise InvalidShapeError("形状无点", mode=shape.mode.value)
    shape_type = _MODE_TO_SHAPE_TYPE.get(shape.mode)
    if shape_type is None:
        raise InvalidShapeError(
            f"模式 {shape.mode.value} 暂不支持 LabelMe 导出", mode=shape.mode.value
        )
    # 矩形只需两个对角点；多边形/画笔/关键点按原样
    if shape.mode is AnnotationMode.RECTANGLE:
        pts = tuple(shape.points[:2])
    else:
        pts = shape.points
    return {
        "label": shape.label,
        "points": [[float(x), float(y)] for x, y in pts],
        "group_id": shape.group_id,
        "shape_type": shape_type,
        # 自定义键：保留原始模式以支持精确往返（既有 loader 忽略）
        "mode": shape.mode.value,
        "flags": {k: v for k, v in shape.flags} if shape.flags else {},
    }


def shape_from_labelme(data: Dict[str, Any]) -> Shape:
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


def labelme_to_shapes(doc: Dict[str, Any]) -> List[Shape]:
    """完整 LabelMe 文档字典 → Shape 列表。（W1: 自 era-2 树移植）"""
    out: List[Shape] = []
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
    image_data: Optional[str] = None,
    channels: Optional[int] = None,
    image_path_list: Optional[List[str]] = None,
    mark: str = "",
) -> Dict[str, Any]:
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


def labelme_to_shapes(doc: Dict[str, Any]) -> List[Shape]:
    """完整 LabelMe 文档字典 → Shape 列表。"""
    shapes_raw = doc.get("shapes") or []
    out: List[Shape] = []
    for item in shapes_raw:
        if not isinstance(item, dict):
            continue
        out.append(shape_from_labelme(item))
    return out


def save_labelme(
    path: Union[str, Path],
    shapes: Sequence[Shape],
    image_path: str,
    image_height: int,
    image_width: int,
    image_data: Optional[str] = None,
    channels: Optional[int] = None,
    image_path_list: Optional[List[str]] = None,
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


def load_labelme(path: Union[str, Path]) -> Dict[str, Any]:
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


def load_labelme_shapes(path: Union[str, Path]) -> List[Shape]:
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
