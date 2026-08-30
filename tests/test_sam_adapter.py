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


# ============================== W21：性能与 device 接线 ============================== #
class _CountingArray(np.ndarray):
    """计 tobytes 次数的 ndarray 视图（观测 set_image 的整图哈希开销）。"""

    tobytes_calls = 0

    def tobytes(self, *args, **kwargs):  # type: ignore[override]
        type(self).tobytes_calls += 1
        return super().tobytes(*args, **kwargs)


class TestSamAdapterSetImagePerf:
    """W21：set_image 快路径——同对象不重复整图 tobytes 哈希。

    回归背景：旧实现对每次调用都 hash(image.tobytes())，1600x1600 图
    每次交互 ~7.7MB 拷贝；to_shapes N 点 N 次。同对象 is 快路径 + 等值
    换对象命中后更新引用，把稳态开销降为指针比较。
    """

    def _counting(self) -> _CountingArray:
        _CountingArray.tobytes_calls = 0
        return np.zeros((32, 32, 3), dtype=np.uint8).view(_CountingArray)

    def test_same_object_second_call_skips_rehash(self):
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        adapter._predictor = mock_predictor
        img = self._counting()
        adapter.set_image(img)
        first = _CountingArray.tobytes_calls
        adapter.set_image(img)  # 同对象：不得再触发整图 tobytes
        assert _CountingArray.tobytes_calls == first, (
            f"同对象第二次 set_image 仍整图哈希（{first} → "
            f"{_CountingArray.tobytes_calls} 次 tobytes）"
        )
        assert mock_predictor.set_image.call_count == 1

    def test_equal_new_object_hits_once_then_object_fast_path(self):
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        adapter._predictor = mock_predictor
        a = self._counting()
        adapter.set_image(a)
        b = np.zeros((32, 32, 3), dtype=np.uint8).view(_CountingArray)
        adapter.set_image(b)  # 等值新对象：哈希一次命中
        mid = _CountingArray.tobytes_calls
        adapter.set_image(b)  # 此后同对象：零哈希
        assert _CountingArray.tobytes_calls == mid
        assert mock_predictor.set_image.call_count == 1

    def test_to_shapes_n_points_single_embed(self):
        """同图 N 点批量 → 底层 set_image 恰一次（点击间不重算 embedding）。"""
        adapter = SamAdapter()
        mock_predictor = MagicMock()
        mock_predictor.predict.return_value = (
            np.array([_SQUARE_MASK]), np.array([0.9]), None,
        )
        adapter._predictor = mock_predictor
        with patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            adapter.to_shapes(_DUMMY_IMG, [((30, 30), 1)] * 4)
        assert mock_predictor.set_image.call_count == 1


class TestSamDeviceWiring:
    """W21：label 页 SAM 加载 device 走 resolve_device 契约（源码守卫）。

    回归背景：_ensure_sam 曾硬编码 device="cpu"（有 GPU 的机器白费）；
    W19 已为 7 个 torch 引擎接入 resolve_device（cuda 可用透传/回退 cpu，
    lite exe 的 CPU torch 自动回退），本守卫防回退到硬编码。
    """

    def test_sam_session_load_uses_resolve_device(self):
        from pathlib import Path
        # W27：SAM 会话五方法自 page.py 抽出至 sam_session.py——守卫
        # 目标随代码迁移（断言本体不变）
        src = (Path(__file__).resolve().parents[1]
               / "gui" / "pages" / "label" / "sam_session.py").read_text(encoding="utf-8")
        load_lines = [ln for ln in src.splitlines() if "adapter.load(" in ln]
        assert load_lines, "label 页应有 adapter.load( 调用"
        assert any("resolve_device" in ln for ln in load_lines), (
            f"SAM 加载须走 resolve_device 契约，实际: {load_lines}"
        )


class TestSamRealCheckpointSmoke:
    """opt-in 真权重冒烟：设置 AVA_SAM_CKPT 指向 sam_vit_{b,l,h}.pth 才跑。

    默认 skip（无权重不伪造；CI 不依赖外部大文件）。权重就位后本用例
    提供真实加载+点击→多边形 的端到端验证。
    """

    def test_real_checkpoint_point_predict(self):
        import os

        ckpt = os.environ.get("AVA_SAM_CKPT")
        if not ckpt or not os.path.exists(ckpt):
            pytest.skip("未设置 AVA_SAM_CKPT（opt-in 真权重冒烟）")

        from models.supervised.device import resolve_device

        model_type = next(
            (t for t in ("vit_b", "vit_l", "vit_h")
             if t in os.path.basename(ckpt)),
            "vit_b",
        )
        adapter = SamAdapter(model_type=model_type)
        adapter.load(ckpt, device=resolve_device("cuda"))

        img = np.zeros((256, 256, 3), dtype=np.uint8)
        img[64:192, 64:192] = 255  # 中央白方块
        poly = adapter.predict_point(img, (128, 128))
        assert len(poly) >= 3, "真权重点击预测应产出多边形"
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        # 轮廓应落在白方块附近（界内 + 容差）
        assert min(xs) >= 32 and max(xs) <= 224
        assert min(ys) >= 32 and max(ys) <= 224
