"""几何工具函数。

为标注画布和 SAM 适配器提供多边形简化、面积计算、矩形归一化等工具。
"""
from __future__ import annotations

import math
from typing import List, Tuple

from labeling.base import Point


def simplify_polyline(
    points: List[Point], epsilon: float = 2.0
) -> List[Point]:
    """Douglas-Peucker 多边形/折线简化。

    Args:
        points: 原始顶点列表。
        epsilon: 简化容差（像素）。距离小于此值的中间点被移除。

    Returns:
        简化后的顶点列表。
    """
    if len(points) < 3:
        return list(points)

    def _perp_dist(
        pt: Point, line_start: Point, line_end: Point
    ) -> float:
        if line_start == line_end:
            return math.hypot(pt[0] - line_start[0], pt[1] - line_start[1])
        dx = line_end[0] - line_start[0]
        dy = line_end[1] - line_start[1]
        norm = math.hypot(dx, dy)
        # 点到直线的垂直距离
        return abs(
            dy * pt[0] - dx * pt[1] + line_end[0] * line_start[1]
            - line_end[1] * line_start[0]
        ) / norm

    def _rdp(pts: List[Point]) -> List[Point]:
        if len(pts) < 3:
            return pts
        # 找距离最远的点
        max_dist = 0.0
        max_idx = 0
        first, last = pts[0], pts[-1]
        for i in range(1, len(pts) - 1):
            d = _perp_dist(pts[i], first, last)
            if d > max_dist:
                max_dist = d
                max_idx = i
        if max_dist > epsilon:
            left = _rdp(pts[: max_idx + 1])
            right = _rdp(pts[max_idx:])
            return left[:-1] + right
        else:
            return [first, last]

    return _rdp(list(points))


def polygon_area(points: List[Point]) -> float:
    """Shoelace 公式计算多边形面积。

    Args:
        points: 多边形顶点列表（至少 3 个点）。

    Returns:
        面积（绝对值）。顶点不足时返回 0。
    """
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0


def normalize_rectangle(
    pt1: Point, pt2: Point
) -> Tuple[Point, Point]:
    """将两个任意角点归一化为 (左上, 右下)。

    Args:
        pt1: 角点 1 (x, y)。
        pt2: 角点 2 (x, y)。

    Returns:
        ((x_min, y_min), (x_max, y_max))
    """
    x1, y1 = pt1
    x2, y2 = pt2
    return (min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))


def point_in_polygon(
    pt: Point, polygon: List[Point]
) -> bool:
    """射线法判断点是否在多边形内部。

    Args:
        pt: 待检测点 (x, y)。
        polygon: 多边形顶点列表。

    Returns:
        True 如果点在多边形内（含边界）。
    """
    x, y = pt
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def bbox_of_points(
    points: List[Point],
) -> Tuple[float, float, float, float]:
    """计算点集的外接矩形。

    Returns:
        (x_min, y_min, x_max, y_max)
    """
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


__all__ = [
    "simplify_polyline",
    "polygon_area",
    "normalize_rectangle",
    "point_in_polygon",
    "bbox_of_points",
]
