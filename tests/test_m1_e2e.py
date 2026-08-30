"""M1 集成 e2e 测试（@pytest.mark.e2e）。

标注 → 训练（冒烟）→ 评估 → 推理 全链路断言。

运行：
    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_m1_e2e.py -m e2e --no-cov -q
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

# 确保 offscreen
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.interfaces_supervised import (
    TaskType,
    TrainConfig,
)


# ============================== fixtures ============================== #
@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication fixture。"""
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def tmp_project(tmp_path):
    """创建临时项目目录。"""
    proj = tmp_path / "test_proj_DET_00001_1700000000"
    for sub in ("images", "annotations", "models", "configs", "results"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    # 写一张测试图像
    import cv2
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[20:80, 20:80] = 128
    cv2.imwrite(str(proj / "images" / "test.png"), img)
    return str(proj)


# ============================== 测试 ============================== #
@pytest.mark.e2e
class TestM1E2E:
    """M1 集成 e2e：页面构建 + 数据流 + 训练冒烟 + 评估 + 推理。"""

    def test_all_pages_construct(self, qapp):
        """所有 5 页可构造。"""
        from gui.pages.data_manage import DataManagePage
        from gui.pages.label.page import LabelPage
        from gui.pages.predict import PredictPage
        from gui.pages.project import ProjectPage
        from gui.pages.train import TrainPage

        for Cls in (LabelPage, DataManagePage, TrainPage, PredictPage, ProjectPage):
            page = Cls()
            assert page.objectName() == "pageBody"
            assert hasattr(page, "retranslate")
            assert hasattr(page, "status_changed")

    def test_build_window(self, qapp):
        """主窗口可构建且注册 5 页。"""
        from gui.main import build_window

        win = build_window()
        assert "label" in win._pages
        assert "data_manage" in win._pages
        assert "train" in win._pages
        assert "predict" in win._pages
        assert "project" in win._pages
        win.deleteLater()

    def test_loss_chart(self, qapp):
        """LossChartWidget 可追加数据并更新。"""
        from gui.widgets.loss_chart import LossChartWidget

        chart = LossChartWidget()
        chart.add_series("loss", "#ef4444")
        chart.append("loss", 1.0, epoch=1)
        chart.append("loss", 0.8, epoch=2)
        chart.append("loss", 0.6, epoch=3)
        chart.update()
        assert "loss" in chart._series
        assert len(chart._series["loss"]) == 3

    def test_train_worker_smoke(self, qapp):
        """TrainWorker 冒烟训练（smoke strategy）。"""
        from gui.pages.train.worker import TrainWorker
        from training.generic_trainer import GenericTrainer

        cfg = TrainConfig(
            task=TaskType.DET, epochs=3, lr=0.001, batch_size=2
        )

        class _SmokeStrategy:
            task = TaskType.DET
            def train_epoch(self, epoch, cfg):
                import math
                return {"loss": round(math.exp(-epoch * 0.3), 4)}
            def save(self, path):
                pass

        trainer = GenericTrainer(cfg.task, _SmokeStrategy())
        worker = TrainWorker(trainer, cfg)
        worker.start()
        worker.wait(10000)  # 最多等 10s
        assert not worker.isRunning()

    def test_metrics_det_map(self):
        """det_map 在完美预测下 mAP=1.0。"""
        from evaluation.metrics_supervised import det_map

        box = [10.0, 10.0, 50.0, 50.0]
        preds = [{"boxes": [box], "scores": [0.95], "labels": [0]}]
        gts = [{"boxes": [box], "labels": [0]}]
        result = det_map(preds, gts, iou_threshold=0.5)
        assert result["mAP"] >= 0.99

    def test_metrics_seg_iou(self):
        """seg_iou 在完全匹配下 IoU=1.0。"""
        from evaluation.metrics_supervised import seg_iou

        mask = np.zeros((50, 50), dtype=np.int32)
        mask[10:40, 10:40] = 1
        assert seg_iou(mask, mask) == pytest.approx(1.0, abs=0.01)

    def test_metrics_abdet_auroc(self):
        """abdet_auroc 在完美可分下 AUROC=1.0。"""
        from evaluation.metrics_supervised import abdet_auroc

        scores = [0.1, 0.2, 0.8, 0.9]
        labels = [0, 0, 1, 1]
        assert abdet_auroc(scores, labels) == pytest.approx(1.0, abs=0.01)

    def test_project_recent_cycle(self, tmp_path):
        """recent 列表 add/remove 周期正确。"""
        from project import recent

        base = str(tmp_path)
        assert recent.recent_list(base) == []
        recent.add_recent(base, "proj_A_DET_00001_1700000000")
        recent.add_recent(base, "proj_B_SEG_00001_1700000001")
        lst = recent.recent_list(base)
        assert lst[0] == "proj_B_SEG_00001_1700000001"
        recent.remove_recent(base, "proj_B_SEG_00001_1700000001")
        assert recent.recent_list(base) == ["proj_A_DET_00001_1700000000"]

    def test_language_switch(self, qapp):
        """切换语言后 tr() 生效。"""
        from gui.core.i18n import set_language, tr

        set_language("ch_CN")
        assert tr("标注") == "标注"
        set_language("en_US")
        assert tr("标注") == "Label"
        set_language("ch_CN")  # 恢复
