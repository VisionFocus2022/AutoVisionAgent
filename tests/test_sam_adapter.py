"""SamAdapter 单元测试（T-AVA-10 验证）。

覆盖 labeling/sam_adapter.py 的 SamAdapter 类：
- loaded 属性（未加载时 False）
- set_image() 未加载时抛 RuntimeError
- predict_point/predict_box — Mock SamPredictor 验证 mask→多边形流程
- to_shapes() 批量接口
- embedding 缓存（同图不重复计算）

策略：Mock segment_anything 和 cv2（均在函数内部延迟导入），
不依赖真实权重文件。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from labeling.base import AnnotationMode, Shape
from labeling.sam_adapter import SamAdapter

_DUMMY_IMG = np.zeros((64, 64, 3), dtype=np.uint8)
_SQUARE_MASK = np.zeros((64, 64), dtype=bool)
_SQUARE_MASK[10:50, 10:50] = True


class TestSamAdapterInit:
    """SamAdapter 构造与初始状态。"""

    def test_default_init(self):
        """构造后 predictor=None, loaded=False。"""
        adapter = SamAdapter()
        assert adapter._predictor is None
        assert adapter.loaded is False
        assert adapter._cached_image_hash is None

    def test_model_type(self):
        """model_type 存储正确。"""
        adapter = SamAdapter(model_type="vit_l")
        assert adapter._model_type == "vit_l"


class TestSamAdapterSetImage:
    """set_image 行为测试。"""

    def test_set_image_without_load_raises(self):
        """未加载权重时 set_image 抛 RuntimeError。"""
        adapter = SamAdapter()
        with pytest.raises(RuntimeError, match="SAM 未加载权重"):
            adapter.set_image(_DUMMY_IMG)

    def test_set_image_caches(self):
        """同图第二次不重复 set_image。"""
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        adapter._predictor = mock_predictor

        adapter.set_image(_DUMMY_IMG)
        assert mock_predictor.set_image.call_count == 1

        # 同图 → 缓存命中，不重复调用
        adapter.set_image(_DUMMY_IMG)
        assert mock_predictor.set_image.call_count == 1

    def test_set_image_different_image(self):
        """不同图 → 重新 set_image。"""
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        adapter._predictor = mock_predictor

        img1 = np.zeros((32, 32, 3), dtype=np.uint8)
        img2 = np.ones((32, 32, 3), dtype=np.uint8)

        adapter.set_image(img1)
        adapter.set_image(img2)
        assert mock_predictor.set_image.call_count == 2


def _make_mock_cv2():
    """创建模拟 cv2 模块（含 findContours / contourArea / 常量）。"""
    mock_cv2 = MagicMock()
    contour_pts = np.array([[[10, 10]], [[50, 10]], [[50, 50]], [[10, 50]]])
    mock_cv2.findContours.return_value = ([contour_pts], None)
    mock_cv2.contourArea.return_value = 1600.0
    mock_cv2.RETR_EXTERNAL = 0
    mock_cv2.CHAIN_APPROX_SIMPLE = 1
    return mock_cv2


class TestSamAdapterPredictPoint:
    """predict_point 行为测试（Mock cv2 + predictor）。"""

    def test_predict_point_returns_polygon(self):
        """点击预测 → mask → 多边形顶点列表。"""
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        mock_predictor.predict.return_value = (
            np.array([_SQUARE_MASK, _SQUARE_MASK, _SQUARE_MASK]),
            np.array([0.9, 0.5, 0.3]),
            None,
        )
        adapter._predictor = mock_predictor

        with patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            poly = adapter.predict_point(_DUMMY_IMG, (30, 30))

        assert len(poly) >= 3
        for pt in poly:
            assert len(pt) == 2

    def test_predict_point_no_contours(self):
        """mask 无轮廓 → 返回空列表。"""
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        mock_predictor.predict.return_value = (
            np.array([np.zeros((64, 64), dtype=bool)]),
            np.array([0.5]),
            None,
        )
        adapter._predictor = mock_predictor

        mock_cv2 = _make_mock_cv2()
        mock_cv2.findContours.return_value = ([], None)
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            poly = adapter.predict_point(_DUMMY_IMG, (30, 30))

        assert poly == []


class TestSamAdapterPredictBox:
    """predict_box 行为测试（Mock cv2 + predictor）。"""

    def test_predict_box_returns_polygon(self):
        """框选预测 → mask → 多边形顶点列表。"""
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        mock_predictor.predict.return_value = (
            np.array([_SQUARE_MASK]),
            np.array([0.95]),
            None,
        )
        adapter._predictor = mock_predictor

        with patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            poly = adapter.predict_box(_DUMMY_IMG, (0, 0, 64, 64))

        assert len(poly) >= 3


class TestSamAdapterToShapes:
    """to_shapes 批量接口测试。"""

    def test_to_shapes_batch(self):
        """批量点击 → Shape 列表。"""
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        mock_predictor.predict.return_value = (
            np.array([_SQUARE_MASK]),
            np.array([0.9]),
            None,
        )
        adapter._predictor = mock_predictor

        with patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            shapes = adapter.to_shapes(
                _DUMMY_IMG,
                [((30, 30), 1), ((20, 20), 1)],
            )

        assert isinstance(shapes, list)
        assert len(shapes) == 2
        for shape in shapes:
            assert isinstance(shape, Shape)
            assert shape.mode == AnnotationMode.POLYGON
            assert len(shape.points) >= 3


class TestSamAdapterLoad:
    """load() 行为测试。"""

    def test_load_calls_segment_anything(self):
        """load() 从 segment_anything 加载 SamPredictor。"""
        adapter = SamAdapter(model_type="vit_b")
        mock_sa = MagicMock()
        mock_sam_model = MagicMock()
        # sam_model_registry 是 dict: {"vit_b": factory(checkpoint=...) -> sam_model}
        mock_factory = MagicMock(return_value=mock_sam_model)
        mock_sa.sam_model_registry = {"vit_b": mock_factory}
        mock_predictor_cls = MagicMock()

        # segment_anything.load 使用 from segment_anything import sam_model_registry, SamPredictor
        # 通过 patch.dict 注入 mock 模块
        mock_sa.SamPredictor = mock_predictor_cls

        with patch.dict("sys.modules", {"segment_anything": mock_sa}):
            adapter.load("/fake/sam_vit_b.pth", device="cpu")

        assert adapter.loaded is True
        mock_factory.assert_called_once_with(checkpoint="/fake/sam_vit_b.pth")
        mock_predictor_cls.assert_called_once_with(mock_sam_model)
