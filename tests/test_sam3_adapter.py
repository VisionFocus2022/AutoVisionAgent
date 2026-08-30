"""Sam3Adapter 单元测试（W46 · TDD RED→GREEN）。

覆盖 labeling/sam3_adapter.py 与 gui/pages/label/sam_session.py 的
resolve_sam3_model_dir 纯函数：
- loaded / set_image 未加载报错 / 图像引用缓存
- load() 经 Fake transformers 模块注入（不触网）
- 提示映射：点击→代偿盒 / 盒直通 / 区域∩矩形硬约束 / 笔划外包盒
- build_amg_detector：文本概念 + score/面积/数量三护栏
- to_shapes 批量
- resolve_sam3_model_dir：env 优先 / config.json 父目录 / 非法回落 None
- 真权重冒烟：AVA_SAM3_DIR opt-in（对齐 AVA_SAM_CKPT 惯例）

策略：_run_instances 为测试接缝（单测替换注入合成掩码，真 cv2 提轮廓，
确定性断言）；不 mock cv2（venv 有真实 opencv）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from labeling.base import AnnotationMode, Shape
from labeling.sam3_adapter import Sam3Adapter, _CLICK_BOX_R, _BRUSH_MARGIN

_DUMMY_IMG = np.zeros((64, 64, 3), dtype=np.uint8)


def _square_mask(size: int = 64, lo: int = 10, hi: int = 50) -> np.ndarray:
    m = np.zeros((size, size), dtype=bool)
    m[lo:hi, lo:hi] = True
    return m


class _FakeRunner:
    """替换 adapter._run_instances：记录调用参数，返回合成实例。"""

    def __init__(self, masks, scores):
        self.masks, self.scores = masks, scores
        self.calls: list = []

    def __call__(self, image, text=None, boxes=None):
        self.calls.append({"image": image, "text": text, "boxes": boxes})
        return self.masks, self.scores


def _make_adapter(masks=None, scores=None):
    """已注入 FakeRunner 的 adapter（绕过 load）。"""
    adapter = Sam3Adapter()
    adapter._model = MagicMock()
    adapter._processor = MagicMock()
    runner = _FakeRunner(
        masks if masks is not None else [_square_mask()],
        scores if scores is not None else [0.9],
    )
    adapter._run_instances = runner
    return adapter, runner


# ---------------------------------------------------------------- 构造与加载


class TestSam3AdapterInit:
    def test_init_not_loaded(self):
        adapter = Sam3Adapter()
        assert adapter.loaded is False
        assert adapter._model is None and adapter._processor is None

    def test_set_image_without_load_raises(self):
        adapter = Sam3Adapter()
        with pytest.raises(RuntimeError, match="SAM3 未加载权重"):
            adapter.set_image(_DUMMY_IMG)

    def test_set_image_same_image_no_error(self):
        """同图重复 set_image（引用/哈希快路径）不抛错。"""
        adapter, _ = _make_adapter()
        adapter.set_image(_DUMMY_IMG)
        adapter.set_image(_DUMMY_IMG)
        equal_copy = _DUMMY_IMG.copy()
        adapter.set_image(equal_copy)

    def test_load_with_fake_transformers(self):
        fake_tf = MagicMock()
        with patch.dict(sys.modules, {"transformers": fake_tf}):
            adapter = Sam3Adapter()
            adapter.load(r"X:/fake/sam3", device="cpu")
        assert adapter.loaded is True
        fake_tf.Sam3Model.from_pretrained.assert_called_once_with(r"X:/fake/sam3")
        fake_tf.Sam3Processor.from_pretrained.assert_called_once_with(r"X:/fake/sam3")
        fake_tf.Sam3Model.from_pretrained.return_value.to.assert_called_once_with(
            device="cpu"
        )
        fake_tf.Sam3Model.from_pretrained.return_value.eval.assert_called_once()

    def test_predict_without_load_raises(self):
        adapter = Sam3Adapter()
        with pytest.raises(RuntimeError, match="SAM3 未加载权重"):
            adapter.predict_point(_DUMMY_IMG, (30, 30))


# ---------------------------------------------------------------- 提示映射


class TestPredictPoint:
    def test_point_converted_to_centered_box(self):
        adapter, runner = _make_adapter()
        poly = adapter.predict_point(_DUMMY_IMG, (30, 30))
        (call,) = runner.calls
        assert call["boxes"] == [[[30 - _CLICK_BOX_R, 30 - _CLICK_BOX_R,
                                   30 + _CLICK_BOX_R, 30 + _CLICK_BOX_R]]]
        assert call["text"] is None
        assert len(poly) >= 3

    def test_point_box_clipped_to_image(self):
        adapter, runner = _make_adapter()
        adapter.predict_point(_DUMMY_IMG, (2, 2))
        (call,) = runner.calls
        (x1, y1, x2, y2) = call["boxes"][0][0]
        assert x1 == 0 and y1 == 0
        assert x2 == 2 + _CLICK_BOX_R and y2 == 2 + _CLICK_BOX_R

    def test_background_click_returns_empty(self):
        """SAM3 无背景点提示——label=0 诚实降级返回空。"""
        adapter, runner = _make_adapter()
        assert adapter.predict_point(_DUMMY_IMG, (30, 30), label=0) == []
        assert runner.calls == []

    def test_nearest_centroid_mask_selected(self):
        """W52 v2：选质心离点击最近的实例（大掩码质心=点击点 30,30，
        小掩码质心 25,25 较远且分高 0.95——旧 argmax 契约已废）。"""
        small = np.zeros((64, 64), dtype=bool)
        small[20:30, 20:30] = True
        adapter, _ = _make_adapter(
            masks=[_square_mask(), small], scores=[0.2, 0.95]
        )
        poly = adapter.predict_point(_DUMMY_IMG, (30, 30))
        xs = [p[0] for p in poly]
        assert max(xs) > 40, "应选质心在点击处的大掩码（_square_mask）"

    def test_no_instances_returns_empty(self):
        adapter, _ = _make_adapter(masks=[], scores=[])
        assert adapter.predict_point(_DUMMY_IMG, (30, 30)) == []


class TestPredictBox:
    def test_box_passthrough(self):
        adapter, runner = _make_adapter()
        poly = adapter.predict_box(_DUMMY_IMG, (5.0, 6.0, 40.0, 44.0))
        (call,) = runner.calls
        assert call["boxes"] == [[[5.0, 6.0, 40.0, 44.0]]]
        assert len(poly) >= 3


class TestPredictPointInBox:
    def test_mask_intersect_rect_hard_constraint(self):
        """掩码越界部分被矩形裁掉——折点严格不越界（W43 语义）。"""
        adapter, runner = _make_adapter()  # mask 10:50 × 10:50
        box = (5, 5, 30, 30)
        poly = adapter.predict_point_in_box(_DUMMY_IMG, (20, 20), box)
        (call,) = runner.calls
        assert call["boxes"] == [[list(box)]]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        assert max(xs) <= 30 and max(ys) <= 30
        # 掩码在矩形内仍有实体（10:30 × 10:30）
        assert min(xs) >= 5 and min(ys) >= 5
        assert len(poly) >= 3

    def test_empty_when_mask_outside_rect(self):
        """掩码与矩形零交集 → 空多边形。"""
        mask = np.zeros((64, 64), dtype=bool)
        mask[40:60, 40:60] = True
        adapter, _ = _make_adapter(masks=[mask], scores=[0.9])
        poly = adapter.predict_point_in_box(_DUMMY_IMG, (10, 10), (0, 0, 20, 20))
        assert poly == []


class TestPredictPoints:
    def test_stroke_bbox_union_with_margin(self):
        adapter, runner = _make_adapter()
        poly, logits = adapter.predict_points(
            _DUMMY_IMG, [(10, 10), (30, 25)], [1, 1]
        )
        (call,) = runner.calls
        (x1, y1, x2, y2) = call["boxes"][0][0]
        assert x1 == 10 - _BRUSH_MARGIN and y1 == 10 - _BRUSH_MARGIN
        assert x2 == 30 + _BRUSH_MARGIN and y2 == 25 + _BRUSH_MARGIN
        assert logits is None  # transformers 后端无 logits 迭代
        assert len(poly) >= 3

    def test_provided_box_union(self):
        adapter, runner = _make_adapter()
        adapter.predict_points(
            _DUMMY_IMG, [(20, 20)], [1], box=(0, 0, 60, 60)
        )
        (call,) = runner.calls
        (x1, y1, x2, y2) = call["boxes"][0][0]
        assert (x1, y1, x2, y2) == (0, 0, 60, 60)

    def test_empty_points_no_call(self):
        adapter, runner = _make_adapter()
        poly, logits = adapter.predict_points(_DUMMY_IMG, [], [])
        assert poly == [] and logits is None
        assert runner.calls == []


# ---------------------------------------------------------------- 概念分割


class TestAmgDetector:
    def test_text_concept_passthrough_and_shapes(self):
        adapter, runner = _make_adapter(masks=[_square_mask()], scores=[0.9])
        detector = adapter.build_amg_detector(label="YS")
        shapes = detector(_DUMMY_IMG)
        (call,) = runner.calls
        assert call["text"] == "YS"
        assert call["boxes"] is None
        assert len(shapes) == 1
        assert shapes[0].mode == AnnotationMode.POLYGON
        assert shapes[0].label == "YS"
        assert len(shapes[0].points) >= 3

    def test_empty_label_defaults_to_defect(self):
        adapter, runner = _make_adapter()
        adapter.build_amg_detector(label="")(_DUMMY_IMG)
        assert runner.calls[0]["text"] == "defect"

    def test_score_threshold_filter(self):
        adapter, _ = _make_adapter(
            masks=[_square_mask(), _square_mask()], scores=[0.9, 0.2]
        )
        detector = adapter.build_amg_detector(iou_thresh=0.5, label="x")
        shapes = detector(_DUMMY_IMG)
        assert len(shapes) == 1

    def test_min_area_filter(self):
        tiny = np.zeros((64, 64), dtype=bool)
        tiny[30:34, 30:34] = True  # 16px² < min_area=64
        adapter, _ = _make_adapter(
            masks=[_square_mask(), tiny], scores=[0.9, 0.9]
        )
        detector = adapter.build_amg_detector(min_area=64, label="x")
        assert len(detector(_DUMMY_IMG)) == 1

    def test_max_masks_truncation_warns(self, caplog):
        masks = [_square_mask(lo=10 + i, hi=30 + i) for i in range(5)]
        adapter, _ = _make_adapter(masks=masks, scores=[0.9] * 5)
        detector = adapter.build_amg_detector(max_masks=2, label="x")
        with caplog.at_level("WARNING"):
            shapes = detector(_DUMMY_IMG)
        assert len(shapes) == 2
        assert any("超上限" in r.message for r in caplog.records)

    def test_degenerate_mask_skipped(self):
        """全零掩码（无轮廓）跳过，不产 Shape。"""
        empty = np.zeros((64, 64), dtype=bool)
        adapter, _ = _make_adapter(masks=[empty], scores=[0.9])
        detector = adapter.build_amg_detector(label="x")
        assert detector(_DUMMY_IMG) == []


class TestToShapes:
    def test_batch_points(self):
        adapter, _ = _make_adapter()
        shapes = adapter.to_shapes(_DUMMY_IMG, [((30, 30), 1)])
        assert len(shapes) == 1
        assert shapes[0].label == "auto"
        assert shapes[0].mode == AnnotationMode.POLYGON


# ---------------------------------------------------------------- 装配解析


class TestResolveSam3ModelDir:
    def test_env_valid_dir(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        assert resolve_sam3_model_dir(str(tmp_path), None) == str(tmp_path)

    def test_env_invalid_falls_back(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        assert resolve_sam3_model_dir(str(tmp_path / "nope"), None) is None

    def test_picked_config_json_with_safetensors(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "model.safetensors").write_bytes(b"x")
        picked = tmp_path / "config.json"
        assert resolve_sam3_model_dir(None, picked) == str(tmp_path)

    def test_picked_config_json_without_safetensors(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        (tmp_path / "config.json").write_text("{}")
        assert resolve_sam3_model_dir(None, tmp_path / "config.json") is None

    def test_picked_pth_is_not_sam3(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        pth = tmp_path / "sam_vit_b.pth"
        pth.write_bytes(b"x")
        assert resolve_sam3_model_dir(None, pth) is None


# ---------------------------------------------------------------- 真权重冒烟


class TestSam3RealWeightsSmoke:
    """opt-in 真权重冒烟：AVA_SAM3_DIR 指向 weights/sam3 才跑。"""

    def test_concept_segmentation_smoke(self):
        ckpt_dir = os.environ.get("AVA_SAM3_DIR")
        if not ckpt_dir:
            pytest.skip("未设置 AVA_SAM3_DIR（opt-in 真权重冒烟）")
        from models.supervised.device import resolve_device

        adapter = Sam3Adapter()
        adapter.load(ckpt_dir, device=resolve_device("cuda"))
        assert adapter.loaded

        img = np.zeros((256, 256, 3), dtype=np.uint8)
        img[:] = (120, 120, 120)
        detector = adapter.build_amg_detector(label="circle", min_area=16)
        shapes = detector(img)
        assert isinstance(shapes, list)
        for s in shapes:
            assert isinstance(s, Shape)
            assert s.mode == AnnotationMode.POLYGON

        # 盒提示路径抽查：输出多边形折点均在图内
        poly = adapter.predict_box(img, (32, 32, 224, 224))
        for x, y in poly:
            assert 0 <= x < 256 and 0 <= y < 256



class TestNearestSelection:
    """W52 实例选择 v2：点击场景选质心最近实例（162 图实测 +0.025 mean、
    零产出 10→1），替代全局 argmax 分数。"""
    def test_nearest_over_argmax(self):
        """高分实例远、低分实例近——选近的（点击意图语义）。"""
        near = np.zeros((64, 64), dtype=bool)
        near[26:34, 26:34] = True   # 质心 ~(30,30) 离点击近
        far = np.zeros((64, 64), dtype=bool)
        far[50:58, 50:58] = True    # 质心 ~(54,54) 远
        adapter, runner = _make_adapter(masks=[far, near], scores=[0.95, 0.10])
        poly = adapter.predict_point(_DUMMY_IMG, (30, 30))
        xs = [p[0] for p in poly]
        assert max(xs) < 40, "应选离点击最近的实例，而非最高分"

    def test_empty_instances(self):
        adapter, _ = _make_adapter(masks=[], scores=[])
        assert adapter.predict_point(_DUMMY_IMG, (30, 30)) == []

    def test_empty_mask_instance_skipped(self):
        """全空掩码实例（nonzero=0）不应被选中为 IndexError 崩溃。"""
        empty = np.zeros((64, 64), dtype=bool)
        good = np.zeros((64, 64), dtype=bool)
        good[20:40, 20:40] = True
        adapter, _ = _make_adapter(masks=[empty, good], scores=[0.9, 0.5])
        poly = adapter.predict_point(_DUMMY_IMG, (30, 30))
        assert len(poly) >= 3


class TestRegionNearestSelection:
    """W53：区域分割（predict_point_in_box）实例选择 v2——质心离点击最近
    （val 162 · GT bbox m=0 实测：mean 0.739→0.755、零产出 4→0、
    ≥0.5 96%→99%），与 predict_point v2 同语义。"""

    def test_region_nearest_over_argmax(self):
        """高分实例远、低分实例近——选近的（点击意图语义移植区域场景）。"""
        near = np.zeros((64, 64), dtype=bool)
        near[26:34, 26:34] = True   # 质心 ~(30,30) 离点击近
        far = np.zeros((64, 64), dtype=bool)
        far[50:58, 50:58] = True    # 质心 ~(54,54) 远且分高
        adapter, _ = _make_adapter(masks=[far, near], scores=[0.95, 0.10])
        poly = adapter.predict_point_in_box(_DUMMY_IMG, (30, 30), (10, 10, 60, 60))
        xs = [p[0] for p in poly]
        assert max(xs) < 40, "应选离点击最近的实例（near），而非最高分（far）"

    def test_region_empty_mask_instance_skipped(self):
        """全空掩码实例（nonzero=0）不应成为区域分割 IndexError 崩溃源。"""
        empty = np.zeros((64, 64), dtype=bool)
        good = np.zeros((64, 64), dtype=bool)
        good[20:40, 20:40] = True
        adapter, _ = _make_adapter(masks=[empty, good], scores=[0.9, 0.5])
        poly = adapter.predict_point_in_box(_DUMMY_IMG, (30, 30), (0, 0, 63, 63))
        assert len(poly) >= 3
