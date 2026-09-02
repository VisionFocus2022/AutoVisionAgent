"""SAM 交互式（点标）模式单元测试（FR-C2/C3，T-M2-03）。

覆盖：
- make_labeler 工厂：INTERACTIVE 可构造
- InteractiveLabeler：Mock SamAdapter 点击→多边形→commit 闭环
- 优雅降级：无 adapter 时不崩溃
- 工厂参数传递 + 属性注入
（AUTO/SAM 全图模式已随 2026-09-01 模式裁剪移除。）
"""
from __future__ import annotations

import pytest

from labeling.base import AnnotationMode
from labeling.modes import make_labeler
from labeling.modes.interactive import InteractiveLabeler

pytestmark = pytest.mark.unit


# =====================================================================
# 工厂测试：make_labeler 不再抛 NotImplementedError
# =====================================================================

class TestFactoryRegistration:
    """make_labeler 能构造 INTERACTIVE 模式。"""

    def test_make_interactive(self) -> None:
        labeler = make_labeler(AnnotationMode.INTERACTIVE, "scratch")
        assert isinstance(labeler, InteractiveLabeler)
        assert labeler.mode is AnnotationMode.INTERACTIVE
        assert labeler.label == "scratch"

    def test_make_interactive_with_adapter_kwarg(self) -> None:
        """通过 **options 传入 sam_adapter。"""
        labeler = make_labeler(
            AnnotationMode.INTERACTIVE, "crack", sam_adapter="fake_adapter"
        )
        assert isinstance(labeler, InteractiveLabeler)

    def test_manual_modes_still_work(self) -> None:
        """手动模式（POLYGON/RECTANGLE）不受影响。"""
        for mode in AnnotationMode.manual_modes():
            labeler = make_labeler(mode, "test")
            assert labeler.mode is mode


# =====================================================================
# Mock SamAdapter
# =====================================================================

class FakeSamAdapter:
    """轻量 SamAdapter 替身（不依赖 segment-anything）。"""

    def __init__(self, polygon: list[tuple[float, float]]) -> None:
        self._polygon = polygon
        self.call_count = 0

    def predict_point(
        self,
        image: object,
        point: tuple[float, float],
        label: int = 1,
    ) -> list[tuple[float, float]]:
        self.call_count += 1
        return list(self._polygon)

    def predict_box(
        self,
        image: object,
        box: tuple[float, float, float, float],
    ) -> list[tuple[float, float]]:
        return list(self._polygon)


class FailingSamAdapter:
    """始终抛异常的 adapter（测试容错）。"""

    def predict_point(self, *args: object) -> list:
        raise RuntimeError("SAM not loaded")


# =====================================================================
# InteractiveLabeler 测试
# =====================================================================

class TestInteractiveLabeler:
    """InteractiveLabeler：点击 → mask → 多边形 → commit。"""

    def test_click_produces_polygon(self) -> None:
        poly = [(10, 10), (50, 10), (50, 50), (10, 50)]
        adapter = FakeSamAdapter(poly)
        labeler = InteractiveLabeler("crack", sam_adapter=adapter, image="fake_img")

        labeler.on_press((30, 30))
        shape = labeler.preview()
        assert shape is not None
        # W46·B：交互式提交形状=POLYGON（工具模式不再上形状——
        # INTERACTIVE 形状会被 LabelMe 导出拒收，保存链裸穿）
        assert shape.mode is AnnotationMode.POLYGON
        assert len(shape.points) == 4

    def test_commit_returns_shape_and_clears(self) -> None:
        poly = [(0, 0), (100, 0), (100, 100)]
        adapter = FakeSamAdapter(poly)
        labeler = InteractiveLabeler("crack", sam_adapter=adapter, image="fake_img")

        labeler.on_press((50, 50))
        shape = labeler.commit()
        assert shape is not None
        assert len(shape.points) == 3
        # 二次 commit 返回 None
        assert labeler.commit() is None

    def test_no_adapter_no_crash(self) -> None:
        """无 adapter 时不崩溃，on_press 无操作。"""
        labeler = InteractiveLabeler("crack")  # 无 adapter, 无 image
        labeler.on_press((50, 50))
        assert labeler.preview() is None
        assert labeler.commit() is None

    def test_no_image_no_crash(self) -> None:
        """有 adapter 但无 image 时不崩溃。"""
        adapter = FakeSamAdapter([(0, 0), (10, 0), (10, 10)])
        labeler = InteractiveLabeler("crack", sam_adapter=adapter)  # 无 image
        labeler.on_press((5, 5))
        assert labeler.preview() is None

    def test_adapter_exception_swallowed(self) -> None:
        """adapter 抛异常时不崩溃。"""
        labeler = InteractiveLabeler(
            "crack",
            sam_adapter=FailingSamAdapter(),
            image="fake",
        )
        labeler.on_press((5, 5))
        assert labeler.preview() is None

    def test_consecutive_clicks_replace(self) -> None:
        """连续点击刷新预测（旧缓存被替换）。"""
        adapter = FakeSamAdapter([(0, 0), (10, 0), (10, 10)])
        labeler = InteractiveLabeler("x", sam_adapter=adapter, image="img")

        labeler.on_press((5, 5))
        first = labeler.preview()
        assert first is not None

        labeler.on_press((20, 20))
        second = labeler.preview()
        assert second is not None
        assert adapter.call_count == 2

    def test_reset_clears_pending(self) -> None:
        adapter = FakeSamAdapter([(0, 0), (10, 0), (10, 10)])
        labeler = InteractiveLabeler("x", sam_adapter=adapter, image="img")
        labeler.on_press((5, 5))
        assert labeler.preview() is not None
        labeler.reset()
        assert labeler.preview() is None
        assert labeler.commit() is None

    def test_set_image_and_set_adapter(self) -> None:
        labeler = InteractiveLabeler("x")
        labeler.set_image("new_img")
        labeler.set_adapter(FakeSamAdapter([(0, 0), (1, 0), (1, 1)]))
        labeler.on_press((0.5, 0.5))
        assert labeler.preview() is not None

    def test_short_polygon_ignored(self) -> None:
        """SAM 返回 <3 点的退化多边形时不缓存。"""
        adapter = FakeSamAdapter([(0, 0), (1, 1)])  # 仅 2 点
        labeler = InteractiveLabeler("x", sam_adapter=adapter, image="img")
        labeler.on_press((0, 0))
        assert labeler.preview() is None


# =====================================================================
# 集成：工厂 + 属性注入
# =====================================================================

class TestFactoryInjection:
    """make_labeler 返回的实例可后续注入依赖。"""

    def test_interactive_inject_after_creation(self) -> None:
        labeler = make_labeler(AnnotationMode.INTERACTIVE, "crack")
        assert isinstance(labeler, InteractiveLabeler)
        # 初始无 adapter/image → 点击无效
        labeler.on_press((5, 5))
        assert labeler.preview() is None
        # 注入后可用
        labeler.set_image("img")
        labeler.set_adapter(FakeSamAdapter([(0, 0), (10, 0), (10, 10)]))
        labeler.on_press((5, 5))
        assert labeler.preview() is not None
