"""W18（TASK-001 / P2-3 退出链补完）：predict 批量推理注册表协作取消。

行为要求：gui/pages/predict/page.py _batch_infer 内 _work 声明 cancel 参数
（run_job 自动注入注册表 threading.Event）；外层批次循环与内层逐图循环
退出条件为 ``self._batch_cancel or cancel.is_set()``。此前 _work 不收
cancel → 退出停机（request_stop_all）只能干等批量跑完全量，注册表协作
取消链在 predict 批量处断链。

本模块用真实线程（生产 run_job，不用 FakeThread）：慢速假引擎 + 12 张图，
主线程 request_stop_all 后断言 worker 远在全量完成前停止（btn_batch 恢复、
处理数 < 总数、注册表在预算内自摘除）。
"""
from __future__ import annotations

import os
import threading
import time

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


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

    def exec(self):
        return 0


class _SlowEngine:
    """慢速假引擎：无 infer_batch → 逐张路径；每张 sleep 使取消窗口可观察。"""

    def __init__(self, per_image_s: float = 0.05) -> None:
        self.per_image_s = per_image_s
        self.calls = 0
        self._lock = threading.Lock()

    def infer(self, img):
        time.sleep(self.per_image_s)
        with self._lock:
            self.calls += 1
        boxes = np.array([[1, 1, 20, 20]], dtype=float)
        return DetectionResult(
            task=TaskType.DET, score=0.9, scores=(0.9,), labels=("crack",),
            boxes=boxes,
        )


def _png(path, w=16, h=12):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


@pytest.mark.unit
def test_batch_infer_stops_on_registry_request_stop_all(
        qapp, tmp_path, monkeypatch):
    """request_stop_all 置位注册表 Event → 批量 worker 协作退出：
    处理数 < 总数、btn_batch 恢复、worker 在停机预算内自摘除（真线程）。"""
    from gui.core import jobs
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage

    total = 12
    d = tmp_path / "batch"
    d.mkdir()
    for i in range(total):
        _png(d / f"img{i:02d}.png")

    engine = _SlowEngine(per_image_s=0.05)
    page = PredictPage()
    page._engine = engine
    page._project_dir = str(tmp_path)  # 结果落 tmp，不污染仓库
    monkeypatch.setattr(pred_mod, "pick_directory", lambda *a, **k: str(d))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", _FakeMsgBox)

    started = time.monotonic()
    page._batch_infer()  # 生产 run_job → 真 daemon 线程

    # 等批量确实开跑（前两张完成即发停机请求）
    deadline = time.monotonic() + 5.0
    while engine.calls < 2 and time.monotonic() < deadline:
        time.sleep(0.005)

    leftover = jobs.request_stop_all(timeout_s=3.0)
    stopped_at = time.monotonic()

    # 主线程事件循环：_batch_done（invoke_main 排队）恢复按钮
    for _ in range(50):
        qapp.processEvents()
        if page.btn_batch.isEnabled():
            break
        time.sleep(0.005)

    full_run_s = total * engine.per_image_s  # 全量纯 sleep 预算（0.6s）
    assert engine.calls < total, (
        f"协作取消后不得继续处理剩余图像（processed={engine.calls}）"
    )
    assert page.btn_batch.isEnabled() is True, "取消后批量按钮必须恢复"
    assert leftover == [], "worker 应在停机预算内自行退出（注册表自摘除）"
    assert stopped_at - started < full_run_s * 2, (
        "worker 应远在全量耗时内停止"
    )
