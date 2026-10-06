"""W1-2 训练历史与模型资产页测试（PRD docs/prd-w1-2-train-history.md）。

- AC-1 存储：append→read 新者优先/坏行跳过/workspace 定向
- AC-2 落账：_on_finished 后记录在册（real/simulated 双形态）；写盘异常不挡
- AC-3 页面渲染 + classes 缺失兜底
- AC-4 模型卡字段（类别表/输入尺寸）
- AC-5 apply_external_model 加载缝 + 推理中拒载
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import pytest

from core import train_history as th
from core.interfaces_supervised import TaskType, TrainConfig


@pytest.fixture()
def hist_ws(monkeypatch, tmp_path):
    """历史存储定向到临时 workspace。"""
    monkeypatch.setattr(
        "project.paths.resolve_base_root", lambda: str(tmp_path), raising=True
    )
    # core.train_history.history_path 调用期 import resolve_base_root —— 模块级
    # from project.paths import resolve_base_root 在函数体内，monkeypatch 生效
    return tmp_path


class TestAc1Storage:
    def test_append_read_newest_first(self, hist_ws):
        th.append_record({"ts": "a", "task": "seg"})
        th.append_record({"ts": "b", "task": "det"})
        recs = th.read_records()
        assert [r["ts"] for r in recs] == ["b", "a"]

    def test_bad_line_skipped(self, hist_ws):
        p = th.history_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{broken json\n")
            fh.write(json.dumps({"ts": "ok"}) + "\n")
        recs = th.read_records()
        assert len(recs) == 1 and recs[0]["ts"] == "ok"

    def test_missing_file_empty(self, hist_ws):
        assert th.read_records() == []

    def test_yaml_classes(self, hist_ws, tmp_path):
        y = tmp_path / "d.yaml"
        y.write_text("names:\n  0: defect\n  1: hole\n", encoding="utf-8")
        assert th.yaml_classes(str(y)) == ["defect", "hole"]
        assert th.yaml_classes("") == []
        assert th.yaml_classes(str(tmp_path / "none.yaml")) == []


@dataclass
class _Artifact:
    task: TaskType
    config: TrainConfig
    weights_path: str = ""
    metrics: dict = field(default_factory=dict)
    epochs_completed: int = 3
    best_metric: float = 1.23


class TestAc2RecordFromArtifact:
    def test_record_fields(self, hist_ws, tmp_path):
        y = tmp_path / "d.yaml"
        y.write_text("names:\n  0: defect\n", encoding="utf-8")
        cfg = TrainConfig(task=TaskType.SEG, epochs=2, data_yaml=str(y),
                          img_size=640, backbone="yolov8n")
        art = _Artifact(TaskType.SEG, cfg, weights_path="w.pt",
                        metrics={"precision": 0.9, "recall": 0.4,
                                 "map50": 0.5, "loss": 1.0})
        rec = th.record_from_artifact(art, n_epochs=100, real=True)
        assert rec["task"] == "seg" and rec["real"] is True
        assert rec["classes"] == ["defect"] and rec["imgsz"] == 640
        assert rec["metrics"] == {"precision": 0.9, "recall": 0.4, "map50": 0.5}
        assert rec["epochs_requested"] == 2 and rec["epochs_completed"] == 100

    def test_train_page_on_finished_appends(self, hist_ws, qapp, monkeypatch):
        from test_gui_train_page import FakeWorker

        from gui.pages.train import page as train_mod

        monkeypatch.setattr(train_mod, "TrainWorker", FakeWorker)
        monkeypatch.setattr(train_mod.TrainPage, "_confirm_simulated",
                            lambda self: True)
        page = train_mod.TrainPage()
        page._make_trainer = lambda cfg: object()  # type: ignore[assignment]
        page._start_training()  # simulated（无 data_yaml）
        recs = th.read_records()
        assert len(recs) == 1 and recs[0]["real"] is False
        assert recs[0]["task"] == "det"

    def test_append_failure_does_not_break_finish(self, hist_ws, qapp, monkeypatch):
        from test_gui_train_page import FakeWorker

        from gui.pages.train import page as train_mod

        monkeypatch.setattr(train_mod, "TrainWorker", FakeWorker)
        monkeypatch.setattr(train_mod.TrainPage, "_confirm_simulated",
                            lambda self: True)
        monkeypatch.setattr("core.train_history.append_record",
                            lambda r: (_ for _ in ()).throw(OSError("disk")))
        page = train_mod.TrainPage()
        page._make_trainer = lambda cfg: object()  # type: ignore[assignment]
        page._start_training()
        assert "训练完成" in page.lbl_log.text(), "落账失败不得挡完成回调"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class TestAc3Ac4PageAndCard:
    @pytest.fixture()
    def page(self, hist_ws, qapp):
        th.append_record({
            "ts": "2026-10-06 12:00:00", "task": "seg", "real": True,
            "epochs_requested": 2, "epochs_completed": 100,
            "weights_path": "w.pt", "data_yaml": "d.yaml",
            "backbone": "yolov8n", "imgsz": 640, "classes": ["defect", "hole"],
            "best_metric": 1.5,
            "metrics": {"precision": 0.9, "recall": 0.4, "map50": 0.5},
        })
        th.append_record({"ts": "t2", "task": "cls", "real": False})
        from gui.pages.train_history import TrainHistoryPage

        p = TrainHistoryPage()
        p.refresh()
        return p

    def test_rows_rendered(self, page):
        assert page.table.rowCount() == 2
        assert page.table.item(0, 1).text() == "cls"  # 新者优先（后追加）
        assert page.table.item(1, 1).text() == "seg"
        assert page.table.item(1, 6).text() in ("真实", "Real")
        assert page.table.item(0, 6).text() in ("模拟", "Simulated")

    def test_card_contains_classes_and_imgsz(self, page, monkeypatch):
        """AC-4：模型卡在屏含类别表与输入尺寸（exec 拦截立即返回）。"""
        from PySide6.QtWidgets import QApplication, QLabel

        import gui.pages.train_history.page as hp

        monkeypatch.setattr(hp.QDialog, "exec", lambda self: 0, raising=True)
        rec = page.table.item(1, 0).data(0x0100)  # seg 记录（行 1）
        page._show_card(rec)
        joined = " ".join(
            w.text() for w in QApplication.allWidgets()
            if isinstance(w, QLabel) and w.text()
        )
        assert "defect" in joined and "hole" in joined, "类别表应在模型卡"
        assert "640" in joined, "输入尺寸应在模型卡"

    def test_load_button_emits_signal(self, page):
        got: list = []
        page.load_requested.connect(lambda p, t: got.append((p, t)))
        rec = {"weights_path": "w.pt", "task": "seg", "real": True}
        page._load_to_predict(rec)
        assert got == [("w.pt", "seg")]
        page._load_to_predict({"task": "seg", "real": True})
        assert len(got) == 1  # 缺权重路径不发射


class TestAc5PredictSeam:
    def test_apply_external_model_sets_task_and_loads(self, qapp, monkeypatch, tmp_path):
        from gui.pages.predict import PredictPage

        page = PredictPage()
        calls: list = []

        class _Eng:
            def load(self, path, device="cpu"):
                calls.append((path, device))


        class _Reg:
            def has(self, t):
                return True

            def get(self, t):
                return _Eng()

            def clear_cache(self, task=None):
                pass

        monkeypatch.setattr(
            "models.supervised.registry.get_default_registry", lambda: _Reg()
        )
        monkeypatch.setattr("gui.core.settings_io.get_device", lambda: "cpu")
        w = tmp_path / "m.pt"
        w.write_bytes(b"x")
        page.apply_external_model(str(w), "seg")
        assert calls and calls[0][0] == str(w)
        assert page.cmb_task.currentData() is TaskType.SEG
        assert page.lbl_model.text() == "m.pt"

    def test_apply_rejected_while_inferring(self, qapp, monkeypatch):
        from gui.core import jobs
        from gui.pages.predict import PredictPage

        page = PredictPage()
        monkeypatch.setattr(
            jobs, "active_jobs", lambda: ["predict_batch_x"]
        )
        msgs: list = []
        page.status_changed.connect(lambda t, a: msgs.append(t))
        page.apply_external_model("x.pt", "det")
        assert any("禁止" in m or "forbidden" in m.lower() for m in msgs)
        assert page._engine is None
