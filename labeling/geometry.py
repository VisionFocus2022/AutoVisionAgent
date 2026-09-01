"""几何工具函数。

为标注画布和 SAM 适配器提供多边形简化、面积计算、矩形归一化等工具。
"""
from __future__ import annotations

import math

from labeling.base import Point

# SAM 掩码→多边形折点容差（W55：2.0→0.5，全 SAM 模式 I/J/B/G 统一消费；
# 校准 2026-09-01：圆 r=25 掩码 raw 84 点 → ε=2.0 简化至 13 / ε=0.5 → 28，
# 顶点密度 3-5 倍且边界贴合掩码边缘，配合编辑模式顶点手柄微调）
SAM_POLY_EPSILON: float = 0.5


def simplify_polyline(
    points: list[Point], epsilon: float = 2.0
) -> list[Point]:
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

    def _rdp(pts: list[Point]) -> list[Point]:
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


def polygon_area(points: list[Point]) -> float:
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
) -> tuple[Point, Point]:
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
    pt: Point, polygon: list[Point]
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
    points: list[Point],
) -> tuple[float, float, float, float]:
    """计算点集的外接矩形。

    Returns:
        (x_min, y_min, x_max, y_max)
    """
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def rectangle_size(pt1: Point, pt2: Point) -> tuple[float, float]:
    """矩形 (宽, 高)。（W1: 自 era-2 树移植，恢复 test_labeling 契约）"""
    (tx, ty), (bx, by) = normalize_rectangle(pt1, pt2)
    return (bx - tx, by - ty)


def polygon_centroid(points: list[Point]) -> Point:
    """多边形质心 (x, y)；退化情况（点数<3 或面积≈0）回退为顶点均值。"""
    n = len(points)
    if n == 0:
        raise ValueError("空点序列无质心")
    if n < 3:
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    area2 = cx = cy = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area2) < 1e-12:
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    return (cx / (3.0 * area2), cy / (3.0 * area2))


def is_closed(points: list[Point]) -> bool:
    """首尾点是否重合（视为已闭合）。"""
    if len(points) < 2:
        return False
    (x1, y1), (x2, y2) = points[0], points[-1]
    return math.hypot(x1 - x2, y1 - y2) < 1e-9


def close_polygon(points: list[Point]) -> tuple[Point, ...]:
    """返回首尾闭合的点序列（已闭合则原样返回）。"""
    pts = tuple(points)
    if len(pts) >= 3 and not is_closed(pts):
        return (*pts, pts[0])
    return pts


# ------------------------------------------------- W55 编辑模式命中检测

# 顶点命中半径（px）——画布缩放下按场景坐标判定，取可见手柄半径
VERTEX_HIT_RADIUS: float = 8.0


def hit_vertex(
    points: list[Point], pt: Point, radius: float = VERTEX_HIT_RADIUS
) -> int | None:
    """命中检测：pt 半径内最近顶点的索引（无命中返回 None）。

    多个顶点落在半径内时取最近者（同距取最小索引）。
    """
    best_idx: int | None = None
    best_d = radius
    for i, v in enumerate(points):
        d = math.hypot(v[0] - pt[0], v[1] - pt[1])
        if d < best_d:
            # 严格小于：平局取最小索引——闭合多边形首/尾同点时命中首点
            best_d = d
            best_idx = i
    return best_idx


def nearest_edge_point(
    points: list[Point], pt: Point
) -> tuple[int, Point] | None:
    """pt 到多边形各边的最近投影点。

    Returns:
        (插入位置, 投影点)：插入位置 = 距离最近边 (points[i]→points[i+1])
        之后的 list.insert 索引；点数 <3 无多边形语义时返回 None。
    """
    n = len(points)
    if n < 3:
        return None
    best: tuple[float, int, Point] | None = None
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        if seg2 < 1e-12:
            t = 0.0
        else:
            t = ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / seg2
            t = min(1.0, max(0.0, t))
        proj = (ax + t * dx, ay + t * dy)
        d = math.hypot(proj[0] - pt[0], proj[1] - pt[1])
        if best is None or d < best[0]:
            best = (d, i + 1, proj)
    assert best is not None
    return best[1], best[2]


__all__ = [
    "SAM_POLY_EPSILON",
    "VERTEX_HIT_RADIUS",
    "simplify_polyline",
    "polygon_area",
    "normalize_rectangle",
    "point_in_polygon",
    "bbox_of_points",
    "rectangle_size",
    "polygon_centroid",
    "is_closed",
    "close_polygon",
    "hit_vertex",
    "nearest_edge_point",
]
