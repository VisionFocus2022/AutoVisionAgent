"""tile_infer_sv 单元测试（W6-T1，sv.InferenceSlicer 对标本树滑窗推理）。

合成图技巧：背景像素值 = x + y*W（int32），假检测器读切片左上角像素即得
切片绝对原点，按"与切片有任意重叠即检出"规则产生切片内检测——跨瓦片
物体会被多瓦片重复检出，两后端都须经 NMS 合并回恰好 N 个物体。
"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
sv = pytest.importorskip("supervision")

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402
from inference.tiling_inferencer import tile_infer, tile_infer_sv  # noqa: E402

W, H = 2400, 1800
TILE, OVERLAP = 640, 96

# 6 物体：5 个单瓦片完整可见 + 1 个（O3）完整落在 x=1088 边界的重叠带
# [1088,1184] 内 → 被相邻两瓦片各完整检出一次（坐标均在切片界内，
# 符合 SAHI"报全框"前提），两后端都须经 NMS 合并为 1
OBJECTS = [
    (100, 100, 300, 260, "crack", 0.92),        # 瓦片 (0,0) 单瓦片
    (1500, 200, 1700, 400, "scratch", 0.85),    # 瓦片 x[1088,1728] 单瓦片
    (1090, 700, 1180, 820, "crack", 0.78),      # 重叠带跨瓦片（两瓦片各检出一次）
    (200, 1300, 520, 1620, "dent", 0.66),       # 瓦片 y[1088,1728] 单瓦片
    (1400, 1500, 1700, 1720, "crack", 0.71),    # 瓦片 (x1088,y1088) 单瓦片
    (2000, 1200, 2250, 1480, "scratch", 0.60),  # 瓦片 x[1632,2272] 单瓦片
]


def _synthetic_image() -> np.ndarray:
    """背景像素值 = x + y*W（编码绝对坐标）。"""
    xs = np.arange(W, dtype=np.int64)
    ys = np.arange(H, dtype=np.int64)
    return (xs[None, :] + ys[:, None] * W).astype(np.int32)


class MapDetector:
    """假引擎：读切片 [0,0] 像素得绝对原点；**仅对完整落入切片的物体报全框**。

    这是 SAHI/InferenceSlicer 的回调前提（真实检测器不输出切片外坐标；
    实测 sv 对越界框会告警并裁剪，被裁半框与邻片全框 IoU 低而双双存活）。
    位于重叠带的物体会被相邻瓦片各完整检出一次 → 两后端都须经 NMS 合并。
    """

    def __init__(self, objects):
        self.objects = objects

    def infer(self, tile, threshold=0.5, labels=None):
        if tile.size == 0 or tile.ndim < 2:
            return DetectionResult(task=TaskType.DET, score=0.0)
        px0 = np.asarray(tile[0, 0]).reshape(-1)[0]  # 3 通道取首通道
        v = int(px0)
        ox, oy = v % W, v // W
        th, tw = tile.shape[:2]
        boxes, scores, labels_out = [], [], []
        for x1, y1, x2, y2, lbl, sc in self.objects:
            if x1 >= ox and y1 >= oy and x2 <= ox + tw and y2 <= oy + th:
                boxes.append([x1 - ox, y1 - oy, x2 - ox, y2 - oy])
                scores.append(sc)
                labels_out.append(lbl)
        if not boxes:
            return DetectionResult(task=TaskType.DET, score=0.0)
        return DetectionResult(
            task=TaskType.DET,
            boxes=np.array(boxes, dtype=np.float32),
            scores=tuple(scores),
            labels=tuple(labels_out),
        )


def _sorted_boxes(boxes):
    return sorted(
        (tuple(round(float(v), 1) for v in b) for b in np.asarray(boxes)),
        key=lambda b: (b[0], b[1]),
    )


def _ground_truth():
    return _sorted_boxes([o[:4] for o in OBJECTS])


@pytest.mark.unit
def test_native_tile_infer_recovers_all_objects():
    """回归锚：既有原生滑窗应找回全部 6 物体（含跨瓦片）且无重复。"""
    results = tile_infer(
        _synthetic_image(), MapDetector(OBJECTS),
        tile_size=TILE, overlap=OVERLAP, merge_iou=0.45,
    )
    assert len(results) == 1
    assert len(results[0].boxes) == 6, f"期望 6 物体，实得 {len(results[0].boxes)}"
    assert _sorted_boxes(results[0].boxes) == _ground_truth()


@pytest.mark.unit
def test_sv_tile_infer_recovers_all_objects():
    """W6-T1：sv.InferenceSlicer 后端同样找回 6 物体、无重复、字段完整。"""
    results = tile_infer_sv(
        _synthetic_image(), MapDetector(OBJECTS),
        slice_wh=TILE, overlap_wh=OVERLAP, iou_threshold=0.45,
    )
    assert len(results) == 1
    merged = results[0]
    assert len(merged.boxes) == 6, f"期望 6 物体，实得 {len(merged.boxes)}"
    assert _sorted_boxes(merged.boxes) == _ground_truth()
    assert set(merged.labels) == {"crack", "scratch", "dent"}
    assert len(merged.scores) == 6
    assert (merged.extra or {}).get("backend") == "sv"


@pytest.mark.unit
def test_sv_tile_infer_small_image_direct():
    """小图不切片直接推理（与原生路径同契约）。"""
    small = np.zeros((280, 320, 3), np.uint8)  # 320x280 < 640：直推
    results = tile_infer_sv(small, MapDetector(OBJECTS), slice_wh=TILE)
    # 原点 (0,0)：仅 O1 (100,100,300,260) 完整落入
    assert len(results) == 1
    assert len(results[0].boxes) == 1
    assert results[0].labels == ("crack",)


@pytest.mark.benchmark
def test_benchmark_native(benchmark):
    """A/B 延迟对比（原生后端）：同图同参（假检测器，测调度与合并开销）。"""
    img = _synthetic_image()
    det = MapDetector(OBJECTS)
    n = benchmark(
        lambda: tile_infer(img, det, tile_size=TILE, overlap=OVERLAP)
    )
    assert len(n[0].boxes) == 6


@pytest.mark.benchmark
def test_benchmark_sv(benchmark):
    """A/B 延迟对比（sv 后端）。"""
    img = _synthetic_image()
    det = MapDetector(OBJECTS)
    s = benchmark(
        lambda: tile_infer_sv(img, det, slice_wh=TILE, overlap_wh=OVERLAP)
    )
    assert len(s[0].boxes) == 6
