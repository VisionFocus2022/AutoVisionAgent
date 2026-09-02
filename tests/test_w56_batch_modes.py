"""W56-B（FR-003）：批量预测模式与并发选项。

对标 SKolpha batchPredictThread（整批后台线程）↔ batch 模式；
batchPredictOnlyOne（逐张即时）↔ incremental 模式（符号级对标 @0x3cf05b0/
0x3cf0503，语义为推断级——实机核对后按 AC-010 回填）。

覆盖：逐张滚动落盘（文件名序）/ 中途增文件续跑 / 取消保留已落盘 /
整批并发结果完整且 JSON 排序稳定 / Mixin 取值 / 页面传参链。
既有语义回归（batch 模式取消不落盘）由 test_w18_batch_cancel 独立守卫。
"""
from __future__ import annotations

import json
import os
import random
import threading
import time

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402
from gui.pages.predict.workers import collect_images  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeMsgBox:
    """QMessageBox 替身：_batch_done 自动弹的统计报表 exec() 不阻塞。"""

    Information = 1

    def __init__(self, parent=None):
        pass

    def setIcon(self, _i):
        pass

    def setWindowTitle(self, _t):
        pass

    def setText(self, _t):
        pass

    def setDetailedText(self, _t):
        pass

    def exec(self):
        return 0


class _Engine:
    """假引擎：逐张 infer（无 infer_batch），可调时延/抖动。"""

    jitter: float = 0.0

    def __init__(self, per_image_s: float = 0.01, seed: int = 7) -> None:
        self.per_image_s = per_image_s
        self.calls = 0
        self._lock = threading.Lock()
        self._rng = random.Random(seed)

    def infer(self, img, threshold=0.5, labels=None):
        delay = self.per_image_s
        if self.jitter:
            delay += self._rng.random() * self.jitter
        time.sleep(delay)
        with self._lock:
            self.calls += 1
        return DetectionResult(
            task=TaskType.DET, score=0.9, scores=(0.9,), labels=("crack",),
            boxes=np.array([[1, 1, 20, 20]], dtype=float),
        )

    def infer_batch(self, images, threshold=0.5, labels=None):
        """批量入口（内部仍逐张——引擎前向串行口径，供并发路径触发）。"""
        return [self.infer(img, threshold=threshold) for img in images]


def _jitter_engine(per_image_s: float, jitter: float) -> _Engine:
    """抖动引擎（并发序打乱用——完成序与提交序不同）。"""
    engine = _Engine(per_image_s=per_image_s)
    engine.jitter = jitter
    return engine


def _png(path, w=16, h=12):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


def _make_page(qapp, tmp_path, engine):
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    page._engine = engine
    page._project_dir = str(tmp_path)  # 结果落 tmp，不污染仓库
    return page


def _wait_done(page, qapp, timeout_s: float = 10.0) -> None:
    """等 _batch_done 槽恢复批量按钮（invoke_main 排队 → processEvents 驱动）。"""
    page.btn_batch.setEnabled(False)  # 直调 run_batch 时模拟 _batch_infer 的状态
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if page.btn_batch.isEnabled():
            return
        time.sleep(0.005)
    raise AssertionError("批量推理在预算内未完成（_batch_done 未恢复按钮）")


def _results_json(root):
    import pathlib

    files = list(pathlib.Path(root).rglob("batch_results.json"))
    assert files, "batch_results.json 未落盘"
    return json.loads(files[0].read_text(encoding="utf-8")), files[0]


@pytest.fixture(autouse=True)
def _msgbox(monkeypatch):
    """统计报表模态框替身（w28 同款接缝：_show_stats 函数内局部导入
    QMessageBox → 模块属性级替换生效；exec() 不阻塞——offscreen 下真
    模态无人关闭会永久挂起，见 W56 排查留痕）。"""
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)


# ============================== 逐张即时模式 ============================== #


@pytest.mark.unit
def test_incremental_writes_sorted_rolling_json(qapp, tmp_path):
    """逐张模式：全部完成后 JSON 存在、条目齐、按文件名序。"""
    from gui.pages.predict.batch_runner import run_batch

    d = tmp_path / "imgs"
    d.mkdir()
    for i in range(5):
        _png(d / f"img{i:02d}.png")
    engine = _Engine(per_image_s=0.01)
    page = _make_page(qapp, tmp_path, engine)

    run_batch(
        page, engine=engine, images=collect_images(str(d)),
        save_dir=str(tmp_path / "results" / "bp1"), threshold=0.5,
        labels_filter=None, save_overlay=False,
        mode="incremental", concurrency=1, images_dir=str(d),
    )
    _wait_done(page, qapp)

    records, _ = _results_json(tmp_path / "results")
    assert len(records) == 5
    files = [r["file"] for r in records]
    assert files == sorted(files), f"落盘须按文件名序，got {files}"


@pytest.mark.unit
def test_incremental_picks_up_files_added_mid_run(qapp, tmp_path):
    """逐张模式运行期间目录新增文件 → 续跑纳入（队列中途可增）。"""
    from gui.pages.predict.batch_runner import run_batch

    d = tmp_path / "imgs"
    d.mkdir()
    for i in range(3):
        _png(d / f"img{i:02d}.png")
    engine = _Engine(per_image_s=0.06)
    page = _make_page(qapp, tmp_path, engine)

    run_batch(
        page, engine=engine, images=collect_images(str(d)),
        save_dir=str(tmp_path / "results" / "bp2"), threshold=0.5,
        labels_filter=None, save_overlay=False,
        mode="incremental", concurrency=1, images_dir=str(d),
    )

    # 前两张完成后追加新文件（初始 3 张 × 0.06s ≈ 0.18s 总窗，0.12s 时介入）
    deadline = time.monotonic() + 5.0
    while engine.calls < 2 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    _png(d / "img10.png")
    _png(d / "img11.png")

    _wait_done(page, qapp, timeout_s=15.0)
    records, _ = _results_json(tmp_path / "results")
    assert len(records) == 5, (
        f"中途新增的 2 张应被续跑纳入（完成 {engine.calls} 张）"
    )


@pytest.mark.unit
def test_incremental_cancel_keeps_partial_results(qapp, tmp_path):
    """逐张模式取消：已处理部分保留在盘（与 batch 模式「取消跳写」相区分）。"""
    from gui.pages.predict.batch_runner import run_batch

    d = tmp_path / "imgs"
    d.mkdir()
    for i in range(6):
        _png(d / f"img{i:02d}.png")
    engine = _Engine(per_image_s=0.05)
    page = _make_page(qapp, tmp_path, engine)

    run_batch(
        page, engine=engine, images=collect_images(str(d)),
        save_dir=str(tmp_path / "results" / "bp3"), threshold=0.5,
        labels_filter=None, save_overlay=False,
        mode="incremental", concurrency=1, images_dir=str(d),
    )

    deadline = time.monotonic() + 5.0
    while engine.calls < 2 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    page._batch_cancel = True

    _wait_done(page, qapp)
    records, _ = _results_json(tmp_path / "results")
    assert 2 <= len(records) < 6, (
        f"取消后应保留已处理部分（processed={engine.calls}）"
    )
    assert engine.calls < 6


# ============================== 整批并发模式 ============================== #


@pytest.mark.unit
def test_batch_concurrency_results_complete_and_sorted(qapp, tmp_path):
    """整批模式并发=4（infer_batch 路径）：结果完整、JSON 按文件名序。"""
    from gui.pages.predict.batch_runner import run_batch

    d = tmp_path / "imgs"
    d.mkdir()
    for i in range(8):
        _png(d / f"img{i:02d}.png")
    engine = _jitter_engine(per_image_s=0.01, jitter=0.03)
    page = _make_page(qapp, tmp_path, engine)

    run_batch(
        page, engine=engine, images=collect_images(str(d)),
        save_dir=str(tmp_path / "results" / "bp4"), threshold=0.5,
        labels_filter=None, save_overlay=False,
        mode="batch", concurrency=4,
    )
    _wait_done(page, qapp)

    records, _ = _results_json(tmp_path / "results")
    assert len(records) == 8
    files = [r["file"] for r in records]
    assert files == sorted(files), "并发完成序落盘前须按文件名重排"


# ============================== Mixin 取值与页面传参 ============================== #


@pytest.mark.unit
def test_batch_options_mixin_values(qapp, tmp_path):
    """模式/并发控件默认值与取值链（默认=整批+串行，稳定口径）。"""
    page = _make_page(qapp, tmp_path, _Engine())
    assert page.batch_mode_value() == "batch"
    assert page.batch_concurrency_value() == 1

    page.cmb_batch_mode.setCurrentIndex(1)
    page.spin_batch_concurrency.setValue(3)
    assert page.batch_mode_value() == "incremental"
    assert page.batch_concurrency_value() == 3


@pytest.mark.unit
def test_page_batch_infer_passes_mode_and_concurrency(qapp, tmp_path, monkeypatch):
    """_batch_infer 把 Mixin 当前值（模式/并发/目录）传入 run_batch。"""
    from gui.pages.predict import batch_runner
    from gui.pages.predict import page as pred_mod

    d = tmp_path / "imgs"
    d.mkdir()
    for i in range(2):
        _png(d / f"img{i:02d}.png")

    page = _make_page(qapp, tmp_path, _Engine())
    page.cmb_batch_mode.setCurrentIndex(1)
    page.spin_batch_concurrency.setValue(2)

    captured = {}

    def _fake_run_batch(p, **kwargs):
        captured.update(kwargs)
        # 模拟立即完成（不启动真线程）
        p._batch_done(0, kwargs.get("images") and len(kwargs["images"]) or 0,
                      False, kwargs.get("mode", "batch"))

    monkeypatch.setattr(batch_runner, "run_batch", _fake_run_batch)
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))

    page._batch_infer()
    assert captured["mode"] == "incremental"
    assert captured["concurrency"] == 2
    assert captured["images_dir"] == str(d)
    assert len(captured["images"]) == 2
