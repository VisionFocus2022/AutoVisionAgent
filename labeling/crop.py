"""裁剪标注几何（W62 / FR-011）：切割线切分既有图形的纯函数。

对标 SKolpha「裁剪标注」（chm 4.5.1.3.9 / docs/skolpha-forensics-wave3.md §3.1）：
- 矩形：切线（过两点的无限直线）命中两条对边 → 取两交点连线中点坐标作轴向
  对齐切（过两宽取中点 x 纵切；过两高取中点 y 横切），一分为二；
  单交点/相邻边/共线/切线过角/两点重合 → 不切（None，SKolpha 同款口径）。
- 多边形：开放环（自动剥收尾重复点）；切线与边**恰 2 个严格交点** → 半平面
  分割为两片；>2 交点（非凸多段穿越）或任一顶点恰在线上 → v1 不切
  （诚实 None，多片切分留 v2——docs/prd-w62-crop-tool.md §4）。
"""
from __future__ import annotations

from collections.abc import Sequence

from labeling.base import Point

_EPS = 1e-9

RectCorners = tuple[Point, Point]


def _line_hit_segment(a: Point, b: Point, p: Point, q: Point) -> Point | None:
    """无限直线 ab 与线段 pq 的严格内部交点（端点/平行/共线 → None）。"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ex, ey = q[0] - p[0], q[1] - p[1]
    denom = dx * ey - dy * ex
    if abs(denom) < _EPS:
        return None
    wx, wy = p[0] - a[0], p[1] - a[1]
    t = (wx * dy - wy * dx) / denom
    if not (_EPS < t < 1.0 - _EPS):
        return None
    return (p[0] + t * ex, p[1] + t * ey)


def _strip_closing_duplicate(points: Sequence[Point]) -> list[Point]:
    """剥除收尾重复点（闭合惯例——多边形落盘/画布可能带首点副本）。"""
    pts: list[Point] = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) >= 2:
        p0, pn = pts[0], pts[-1]
        if abs(p0[0] - pn[0]) < _EPS and abs(p0[1] - pn[1]) < _EPS:
            pts = pts[:-1]
    return pts


def split_rectangle_by_line(
    rect: RectCorners, a: Point, b: Point
) -> list[RectCorners] | None:
    """矩形被过 a-b 的无限直线切分。

    Returns:
        两个新矩形（(左上, 右下) 归一化角点，轴向对齐切）；不可切 → None。
    """
    if abs(a[0] - b[0]) < _EPS and abs(a[1] - b[1]) < _EPS:
        return None
    (x1, y1), (x2, y2) = rect
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    hits: dict[str, Point] = {}
    for name, p, q in (
        ("top", (x1, y1), (x2, y1)),
        ("bottom", (x1, y2), (x2, y2)),
        ("left", (x1, y1), (x1, y2)),
        ("right", (x2, y1), (x2, y2)),
    ):
        hit = _line_hit_segment(a, b, p, q)
        if hit is not None:
            hits[name] = hit
    if set(hits) == {"top", "bottom"}:
        mid_x = (hits["top"][0] + hits["bottom"][0]) / 2.0
        return [((x1, y1), (mid_x, y2)), ((mid_x, y1), (x2, y2))]
    if set(hits) == {"left", "right"}:
        mid_y = (hits["left"][1] + hits["right"][1]) / 2.0
        return [((x1, y1), (x2, mid_y)), ((x1, mid_y), (x2, y2))]
    return None


def split_polygon_by_line(
    points: Sequence[Point], a: Point, b: Point
) -> list[list[Point]] | None:
    """开放环多边形被过 a-b 的无限直线切分（2 严格交点 → 两片）。

    Returns:
        两个新多边形点列（开放环，各 ≥3 点）；不可切 → None。
    """
    if abs(a[0] - b[0]) < _EPS and abs(a[1] - b[1]) < _EPS:
        return None
    ring = _strip_closing_duplicate(points)
    n = len(ring)
    if n < 3:
        return None
    dx, dy = b[0] - a[0], b[1] - a[1]
    sides: list[int] = []
    for p in ring:
        cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
        if abs(cross) < _EPS:
            return None  # 顶点恰在切线上：v1 规避歧义（微移即可）
        sides.append(1 if cross > 0 else -1)
    crossings = sum(
        1 for i in range(n) if sides[i] * sides[(i + 1) % n] < 0
    )
    if crossings != 2:
        return None
    left: list[Point] = []
    right: list[Point] = []
    for i in range(n):
        if sides[i] > 0:
            left.append(ring[i])
        else:
            right.append(ring[i])
        nxt = (i + 1) % n
        if sides[i] * sides[nxt] < 0:
            hit = _line_hit_segment(a, b, ring[i], ring[nxt])
            if hit is None:  # 严格异号边必有内交点——防御性兜底
                return None
            left.append(hit)
            right.append(hit)
    if len(left) < 3 or len(right) < 3:
        return None
    return [left, right]


__all__ = ["split_polygon_by_line", "split_rectangle_by_line"]
