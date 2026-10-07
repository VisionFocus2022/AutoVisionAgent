"""W2-2 PR 曲线与阈值推荐测试（PRD docs/prd-w2-2-pr-threshold.md）。

- AC-1 曲线数学（网格 P/R/F1 精确值 + best_f1 + 空数据）
- AC-2 采集（fake 引擎 + tmp LabelMe；矩形/多边形 GT；贪心独占匹配）
- AC-3 页面（双线渲染/推荐标签/写入信号/非 det 禁用）
- AC-4 报告落盘（workspace eval_reports JSON 字段）
- AC-5 predict set_threshold 生效
"""
from __future__ import annotations

import json
import os

import pytest

from evaluation.pr_curve import (
    best_f1_point,
    collect_detections,
    pr_curve,
    save_eval_report,
)


class TestAc1CurveMath:
    def test_grid_values_exact(self):
        # 3 GT；检出：TP@(0.9), TP@(0.6), FP@(0.7)
        collected = {"detections": [(0.9, True), (0.7, False), (0.6, True)],
                     "n_gt": 3, "n_images": 1}
        pts = pr_curve(collected, grid=[0.5, 0.65, 0.8])
        by_t = {p["threshold"]: p for p in pts}
        # t=0.5: TP=2 FP=1 → P=2/3 R=2/3
        assert by_t[0.5]["precision"] == pytest.approx(2 / 3)
        assert by_t[0.5]["recall"] == pytest.approx(2 / 3)
        # t=0.65: 计入 0.9(TP)+0.7(FP) → TP=1 FP=1 → P=0.5 R=1/3
        assert by_t[0.65]["precision"] == 0.5
        assert by_t[0.65]["recall"] == pytest.approx(1 / 3)
        # t=0.8: TP=1 FP=0 → P=1.0 R=1/3
        assert by_t[0.8]["precision"] == 1.0
        assert by_t[0.8]["recall"] == pytest.approx(1 / 3)
        assert by_t[0.5]["f1"] == pytest.approx(2 / 3)

    def test_best_f1_picks_max(self):
        pts = [
            {"threshold": 0.1, "precision": 0.5, "recall": 0.9, "f1": 0.64},
            {"threshold": 0.4, "precision": 0.9, "recall": 0.8, "f1": 0.85},
            {"threshold": 0.8, "precision": 1.0, "recall": 0.3, "f1": 0.46},
        ]
        best = best_f1_point(pts)
        assert best["available"] is True and best["threshold"] == 0.4

    def test_empty_input(self):
        best = best_f1_point([])
        assert best["available"] is False
        pts = pr_curve({"detections": [], "n_gt": 0, "n_images": 0},
                       grid=[0.5])
        # 无 GT：R=0，无检出：P=1（约定）——不炸即可判
        assert pts[0]["recall"] == 0.0


class _FakeEngine:
    """按图名返回预设检出（boxes+scores）。"""

    def __init__(self, boxes_by_stem):
        self._by = boxes_by_stem

    def infer(self, img, threshold=0.5):
        stem = os.path.splitext(os.path.basename(
            getattr(img, "name", "") or str(img)))[0]
        boxes, scores = self._by.get(stem, ([], []))
        import numpy as np

        r = type("R", (), {})()
        r.task = None
        r.score = max(scores) if scores else 0.0
        r.scores = tuple(scores)
        r.labels = ()
        r.boxes = np.array(boxes) if boxes else None
        return r


class TestAc2Collect:
    def _make_gt(self, d):
        (d / "annotations").mkdir(exist_ok=True)
        # 图像放标注目录旁（gt_dir 的兄弟 base=gt_dir 父）
        import cv2
        import numpy as np

        img = np.zeros((100, 100, 3), np.uint8)
        cv2.imwrite(str(d / "a.png"), img)
        cv2.imwrite(str(d / "b.png"), img)
        (d / "annotations" / "a.json").write_text(json.dumps({
            "imagePath": "a.png",
            "shapes": [
                {"label": "defect", "shape_type": "rectangle",
                 "points": [[10, 10], [30, 30]]},
                {"label": "defect", "shape_type": "polygon",
                 "points": [[50, 50], [70, 50], [70, 70], [50, 70]]},
            ],
        }), encoding="utf-8")
        (d / "annotations" / "b.json").write_text(json.dumps({
            "imagePath": "b.png",
            "shapes": [
                {"label": "defect", "shape_type": "rectangle",
                 "points": [[5, 5], [25, 25]]},
            ],
        }), encoding="utf-8")

    def test_collect_tp_fp_and_greedy(self, tmp_path):
        self._make_gt(tmp_path)
        eng = _FakeEngine({
            "a": ([(10, 10, 30, 30), (60, 60, 80, 80), (90, 90, 99, 99)],
                  [0.9, 0.8, 0.7]),
            "b": ([(50, 50, 90, 90)], [0.6]),  # 不匹配 b 的 GT → FP
        })
        imread = lambda p: type("P", (), {"name": os.path.basename(p)})()  # noqa: E731
        r = collect_detections(str(tmp_path / "annotations"),
                               str(tmp_path / "annotations"),
                               engine=eng, imread=imread)
        assert r["n_gt"] == 3 and r["n_images"] == 2
        tps = [s for s, m in r["detections"] if m]
        fps = [s for s, m in r["detections"] if not m]
        # a 图：0.9 完中 GT1=TP；0.8 框(60-80)对 GT2(50-70) IoU=0.14<0.5=FP
        # （偏移框不得算命中——这正是阈值分析要暴露的形态）；0.7 纯 FP
        assert sorted(tps) == [0.9]
        assert sorted(fps) == [0.6, 0.7, 0.8]


class TestAc3Ac4Ac5Page:
    @pytest.fixture(scope="class")
    def qapp(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def test_page_pr_ready_renders_and_signal(self, qapp, monkeypatch):
        from gui.pages.eval_.page import EvalPage

        page = EvalPage()
        got: list[float] = []
        page.threshold_apply.connect(got.append)
        pr = [{"threshold": 0.3, "precision": 0.8, "recall": 0.7, "f1": 0.75},
              {"threshold": 0.5, "precision": 0.9, "recall": 0.6, "f1": 0.72}]
        page._on_pr_ready(pr, {"available": True, **pr[0]}, "x/eval_1.json")
        assert len(page._pr_chart._series.get("precision", [])) == 2
        assert len(page._pr_chart._series.get("recall", [])) == 2
        assert "0.30" in page._pr_rec_label.text()
        assert page._pr_apply_btn.isEnabled()
        page._apply_threshold()
        assert got == [0.3]

    def test_page_pr_unavailable_disables_apply(self, qapp):
        from gui.pages.eval_.page import EvalPage

        page = EvalPage()
        page._on_pr_ready([], {"available": False, "reason": "无"}, "x.json")
        assert not page._pr_apply_btn.isEnabled()

    def test_predict_set_threshold(self, qapp):
        from gui.pages.predict import PredictPage

        page = PredictPage()
        page.set_threshold(0.37)
        assert page.spin_threshold.value() == pytest.approx(0.37)

    def test_report_saved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "project.paths.resolve_base_root", lambda: str(tmp_path)
        )
        pr = pr_curve({"detections": [(0.9, True)], "n_gt": 1, "n_images": 1},
                      grid=[0.5])
        best = best_f1_point(pr)
        path = save_eval_report([("mAP", 0.5, "note")], pr, best)
        from pathlib import Path
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        assert doc["rows"] == [["mAP", 0.5, "note"]]  # JSON 元组→列表
        assert doc["best_f1"]["available"] is True
        assert len(doc["pr_curve"]) == 1
        assert os.path.basename(path).startswith("eval_")
