"""批量推理后处理并发 A/B 基准（W61 · FR-002 —— NFR-001/D-14 收口）。

测什么：W56 FR-003 的并发选项（ThreadPoolExecutor 仅并行后处理层——
叠加渲染/产物写，引擎前向恒串行）。本脚本用「快引擎 + 开叠加渲染」
把负载集中到被并行化的后处理层，对比 concurrency=1 vs 4 的墙钟时间。

口径（宽容，不做硬门禁断言——测试环境噪声，D-14 裁决）：
- 记录实测数字到 docs/benchmarks/（本脚本 stdout 追加格式见末尾）；
- 判读标准：并发=4 应「不劣化」（<=1x）；显著变慢（>1.2x）才视为异常。

运行（源码态）::

    .venv/Scripts/python.exe benchmarks/bench_batch_concurrency.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402


class _FakeMsgBox:
    Information = 1

    def __init__(self, *a):
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


# W56 排坑同款：_show_stats 为函数内局部导入 + 实例构造 + 模态 exec()——
# 必须**模块属性级**替换（EXP-20260902c），类方法级替换不命中
import PySide6.QtWidgets as _qtw  # noqa: E402

_qtw.QMessageBox = _FakeMsgBox


class _FastEngine:
    """零耗时假引擎——把墙钟全部留给后处理层（被并行面）。"""

    def infer(self, img, threshold=0.5, labels=None):
        return DetectionResult(
            task=TaskType.DET, score=0.9, scores=(0.9,), labels=("crack",),
            boxes=np.array([[1, 1, 60, 40]], dtype=float),
        )


def _png(path: Path, w=640, h=480):
    import cv2

    ok, buf = cv2.imencode(
        ".jpg", (np.random.rand(h, w, 3) * 255).astype("uint8")
    )
    assert ok
    path.write_bytes(buf.tobytes())


def _run_once(app, page, images, save_dir, concurrency: int) -> float:
    from gui.pages.predict.batch_runner import run_batch

    page._results.clear()
    page._batch_cancel = False
    page.btn_batch.setEnabled(False)
    t0 = time.monotonic()
    run_batch(
        page, engine=page._engine, images=images, save_dir=save_dir,
        threshold=0.5, labels_filter=None,
        save_overlay=True, overlay_renderer=page._render_for_bench,
        mode="batch", concurrency=concurrency,
    )
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        app.processEvents()
        if page.btn_batch.isEnabled():
            break
        time.sleep(0.02)
    return time.monotonic() - t0


def main() -> int:
    import faulthandler
    faulthandler.dump_traceback_later(150, exit=True)
    print('bench: start', flush=True)
    app = QApplication.instance() or QApplication([])
    from gui.pages.predict.page import PredictPage
    from inference.sv_bridge import render_result

    n = 50
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "imgs"
        d.mkdir()
        for i in range(n):
            _png(d / f"img{i:02d}.jpg")
        print('bench: images ready', flush=True)

        page = PredictPage()
        page._engine = _FastEngine()
        page._project_dir = td
        page._render_for_bench = render_result

        from gui.pages.predict.workers import collect_images

        images = collect_images(str(d))
        assert len(images) == n

        # 预热一轮（JIT/cv2 首次编解码/导入链摊销）
        _run_once(app, page, images[:5], str(Path(td) / "warm"), 1)
        print('bench: warm done', flush=True)

        print('bench: serial start', flush=True)
        t_serial = _run_once(
            app, page, images, str(Path(td) / "c1"), concurrency=1)
        print('bench: parallel start', flush=True)
        t_parallel = _run_once(
            app, page, images, str(Path(td) / "c4"), concurrency=4)

        ratio = t_parallel / t_serial if t_serial > 0 else float("inf")
        print(f"n={n} save_overlay=True")
        print(f"concurrency=1: {t_serial:.2f}s")
        print(f"concurrency=4: {t_parallel:.2f}s")
        print(f"ratio(parallel/serial)={ratio:.2f}x")
        verdict = "OK（不劣化）" if ratio <= 1.2 else "DEGRADED（>1.2x，需查）"
        print(f"verdict={verdict}")
        print(
            "append-to: docs/benchmarks/batch-concurrency-baseline-w61.md "
            f"| {time.strftime('%Y-%m-%d %H:%M')} n={n} "
            f"serial={t_serial:.2f}s parallel={t_parallel:.2f}s ratio={ratio:.2f}x {verdict}"
        )
        page.deleteLater()
        return 0 if ratio <= 1.2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
