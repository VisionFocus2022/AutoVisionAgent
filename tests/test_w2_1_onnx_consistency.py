"""W2-1 ONNX 一致性校验 + 模型卡随包测试（PRD docs/prd-w2-1-onnx-consistency.md）。

- AC-1 compare_boxes 三态（完美/部分/不相交/空对空/幻觉）
- AC-2 一致性：fake predictor 完美→ok；漏检→ok=False；坏路径显式失败不抛
- AC-3 卡片：历史命中→字段入卡；无记录→最小卡不炸
- AC-4 真链集成：det 真训练→export_onnx→校验≥0.95→卡片同目录含 defect
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from exporter.onnx_consistency import (
    compare_boxes,
    onnx_consistency_check,
    write_model_card,
)


class TestAc1CompareBoxes:
    def test_perfect_partial_disjoint(self):
        ref = [(0, 0, 10, 10), (20, 20, 30, 30), (40, 40, 50, 50)]
        assert compare_boxes(ref, list(ref)) == 1.0
        assert compare_boxes(ref, ref[:2]) == pytest.approx(2 / 3)
        assert compare_boxes(ref, [(100, 100, 110, 110)]) == 0.0

    def test_empty_semantics(self):
        assert compare_boxes([], []) == 1.0, "双端同无检出=一致"
        assert compare_boxes([], [(0, 0, 5, 5)]) == 0.0, "pt 无而 onnx 幻觉"

    def test_greedy_no_reuse(self):
        ref = [(0, 0, 10, 10), (0, 0, 10, 12)]
        assert compare_boxes(ref, [(0, 0, 10, 11)]) == 0.5, "一 cand 不得配两 ref"


class TestAc2ConsistencyCheck:
    def _mk_predictor(self, pt_boxes, onnx_boxes):
        def make(weights, threshold):
            boxes = pt_boxes if weights.endswith(".pt") else onnx_boxes

            def _p(img):
                return list(boxes)

            return _p

        return make

    def test_perfect_match_ok(self, tmp_path):
        pt, onnx = tmp_path / "m.pt", tmp_path / "m.onnx"
        pt.write_bytes(b"x")
        onnx.write_bytes(b"x")
        boxes = [(0, 0, 10, 10)]
        r = onnx_consistency_check(
            str(pt), str(onnx), images=["a.png"],
            predictor=self._mk_predictor(boxes, boxes),
        )
        assert r["ok"] is True and r["match_rate"] == 1.0 and r["n_images"] == 1

    def test_missing_detection_fails_threshold(self, tmp_path):
        pt, onnx = tmp_path / "m.pt", tmp_path / "m.onnx"
        pt.write_bytes(b"x")
        onnx.write_bytes(b"x")
        r = onnx_consistency_check(
            str(pt), str(onnx), images=["a.png"],
            predictor=self._mk_predictor(
                [(0, 0, 10, 10), (20, 20, 30, 30), (40, 40, 50, 50)],
                [(0, 0, 10, 10)],
            ),
        )
        assert r["ok"] is False and r["match_rate"] == pytest.approx(1 / 3, abs=1e-3)

    def test_bad_paths_fail_explicitly(self, tmp_path):
        r = onnx_consistency_check(
            str(tmp_path / "nope.pt"), str(tmp_path / "nope.onnx")
        )
        assert r["ok"] is False and "error" in r, "坏路径显式失败不抛出"

    def test_predictor_exception_becomes_failure(self, tmp_path):
        pt, onnx = tmp_path / "m.pt", tmp_path / "m.onnx"
        pt.write_bytes(b"x")
        onnx.write_bytes(b"x")

        def make(weights, threshold):
            def _p(img):
                raise RuntimeError("onnxruntime boom")

            return _p

        r = onnx_consistency_check(
            str(pt), str(onnx), images=["a.png"], predictor=make
        )
        assert r["ok"] is False and "boom" in r["error"]


class TestAc3ModelCard:
    def test_card_with_history(self, tmp_path, monkeypatch):
        from core import train_history as th

        monkeypatch.setattr(
            "project.paths.resolve_base_root", lambda: str(tmp_path)
        )
        pt, onnx = tmp_path / "m.pt", tmp_path / "m.onnx"
        pt.write_bytes(b"x")
        th.append_record({
            "ts": "t", "task": "det", "real": True, "weights_path": str(pt),
            "classes": ["defect"], "imgsz": 640, "backbone": "yolov8n",
            "metrics": {"map50": 0.5}, "epochs_completed": 100,
        })
        path = write_model_card(str(pt), str(onnx), "det")
        assert path == str(tmp_path / "m_model_card.json")
        card = json.loads(Path(path).read_text(encoding="utf-8"))
        assert card["train_classes"] == ["defect"]
        assert card["train_imgsz"] == 640 and card["task"] == "det"

    def test_card_without_history_minimal(self, tmp_path, monkeypatch):

        monkeypatch.setattr(
            "project.paths.resolve_base_root", lambda: str(tmp_path)
        )
        pt, onnx = tmp_path / "x.pt", tmp_path / "x.onnx"
        pt.write_bytes(b"x")
        path = write_model_card(str(pt), str(onnx), "seg")
        card = json.loads(Path(path).read_text(encoding="utf-8"))
        assert card["task"] == "seg" and "train_classes" not in card
        assert card["onnx_path"].endswith("x.onnx")


@pytest.mark.integration
class TestAc4RealChain:
    def test_train_export_consistency_card(self, tmp_path, monkeypatch):
        """真链：det 训练(floor=0)→export_onnx→一致性≥0.95→卡含 defect。"""
        import cv2
        import numpy as np

        from core import train_history as th
        from core.interfaces_supervised import TaskType, TrainConfig
        from models.supervised.engines.det_yolo import DetYoloEngine

        monkeypatch.setattr(
            "project.paths.resolve_base_root", lambda: str(tmp_path / "ws")
        )
        root = tmp_path / "yolo"
        for sub in ("labels/train", "labels/val", "images/train", "images/val"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        img = np.zeros((96, 96, 3), np.uint8)
        img[24:72, 24:72] = 140
        cv2.imwrite(str(root / "images/train/a.png"), img)
        cv2.imwrite(str(root / "images/val/b.png"), img)
        (root / "labels/train/a.txt").write_text("0 0.5 0.5 0.5 0.5\n")
        (root / "labels/val/b.txt").write_text("0 0.5 0.5 0.5 0.5\n")
        yaml_p = root / "data.yaml"
        yaml_p.write_text(
            f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\n"
            "nc: 1\nnames:\n  0: defect\n"
        )
        eng = DetYoloEngine()
        cfg = TrainConfig(task=TaskType.DET, epochs=1, small_data_epoch_floor=0,
                          data_yaml=str(yaml_p), device="cpu", amp=False,
                          output_dir=str(tmp_path / "out"))
        eng.train_epoch(1, cfg)
        best = os.path.join(eng._train_output_dir, "weights", "best.pt")
        assert os.path.isfile(best), "训练产物缺失"
        th.append_record(th.record_from_artifact(
            type("A", (), {
                "task": TaskType.DET, "config": cfg, "weights_path": best,
                "metrics": {}, "epochs_completed": 1, "best_metric": 0.0,
            })(), 1, True,
        ))

        from exporter.onnx_consistency import safe_load_model
        from exporter.supervised_exporter import SupervisedExporter

        model = safe_load_model(best)  # 已解包为 nn.Module 并 float()
        model.eval()
        onnx_p = str(tmp_path / "out/det.onnx")
        SupervisedExporter().export_onnx(model, "det", onnx_p)
        assert os.path.isfile(onnx_p)

        from exporter.onnx_consistency import sample_images_from_history

        imgs = sample_images_from_history(best)
        assert imgs, "历史样本图缺失"
        cons = onnx_consistency_check(best, onnx_p, images=imgs)
        assert cons["ok"] is True, f"真链一致性未过: {cons}"
        assert cons["match_rate"] >= 0.95

        card_p = write_model_card(best, onnx_p, "det")
        card = json.loads(Path(card_p).read_text(encoding="utf-8"))
        assert card.get("train_classes") == ["defect"]
