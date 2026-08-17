"""W15-J2 迁移守卫 + P2-19 关键操作日志 + P2-22 docstring 诚实化（RED 先行）。

J2（P2-1 迁移批次 A）：data_manage/eval_/flaw_gen 三页四处裸
threading.Thread 统一改经 gui.core.jobs.run_job 调度。本文件源码守卫
断言锁死"不得回退到手搓线程"——RED：迁移前 threading.Thread 仍在
三页源码（data_manage:379/485、eval_:290、flaw_gen:210）→ 红。

P2-19：三页关键操作 logger.info 留痕（data_manage 导入完成/划分完成、
eval_ 评估开始/完成、flaw_gen 生成开始/完成）——RED：迁移前三页 0 条
INFO 操作日志。不在逐图循环内刷屏（flaw_gen 逐图仅 invoke_main 进度，
无 logger 调用）。

P2-22：data_manage 页 docstring 不得宣称对接不存在的 DataManager
（grep `class DataManager\\b` 全仓 0 命中），须如实描述现有 worker 路径。
"""
from __future__ import annotations

import json
import logging
import os
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    """与既有三页测试同款接缝（tests/test_gui_datamanage_page.py:29）：同步执行。"""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t: self._t(*self._a, **self._k)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


def _png(path, w=32, h=24):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


def _labelme(path, name="a.png", box=(4, 4, 20, 16)):
    path.write_text(
        json.dumps({
            "imagePath": name,
            "shapes": [{"label": "crack", "shape_type": "rectangle",
                        "points": [[box[0], box[1]], [box[2], box[3]]]}],
        }),
        encoding="utf-8",
    )


# ============================== 迁移守卫（P2-1 批次 A） ============================== #
_PAGE_FILES = [
    "gui/pages/data_manage/page.py",
    "gui/pages/eval_/page.py",
    "gui/pages/flaw_gen/page.py",
]


def _src(rel: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.unit
def test_guard_pages_no_bare_thread_and_use_run_job():
    """RED：三页源码不得残留 threading.Thread 直调，必须经 run_job。"""
    for rel in _PAGE_FILES:
        src = _src(rel)
        assert "threading.Thread" not in src, (
            f"{rel} 残留裸线程直调（P2-1 批次 A：后台任务须统一经 "
            "gui.core.jobs.run_job，含注册表登记/协作取消/异常路由）"
        )
        assert "run_job" in src, f"{rel} 未接入 gui.core.jobs.run_job"


# ============================== P2-22 docstring 诚实化 ============================== #
@pytest.mark.unit
def test_datamanage_docstring_no_fake_datamanager_claim():
    """RED：docstring 不得宣称对接不存在的 DataManager，须如实提及 workers。"""
    from gui.pages.data_manage import page as dm_mod

    doc = dm_mod.__doc__ or ""
    assert "DataManager" not in doc, (
        "P2-22：全仓不存在 class DataManager，宣称失实"
    )
    assert "workers" in doc, "P2-22：须如实描述 gui.pages.data_manage.workers 路径"


# ============================== P2-19 关键操作日志 ============================== #
@pytest.fixture
def proj(tmp_path):
    img_dir = tmp_path / "proj" / "images"
    img_dir.mkdir(parents=True)
    _png(img_dir / "a.png")
    return tmp_path / "proj"


@pytest.fixture
def dm_page(qapp, proj):
    from gui.pages.data_manage.page import DataManagePage

    page = DataManagePage()
    page.set_project_dir(str(proj))
    return page


@pytest.mark.unit
def test_import_completion_logged(
    dm_page, fake_threads, monkeypatch, tmp_path, qapp, caplog
):
    """P2-19 RED：图像导入完成须 logger.info 留痕。"""
    from gui.pages.data_manage import page as dm_mod

    src = tmp_path / "src"
    src.mkdir()
    _png(src / "new.png")
    monkeypatch.setattr(dm_mod, "pick_directory", lambda *a, **k: str(src))

    with caplog.at_level(logging.INFO, logger="gui.pages.data_manage.page"):
        dm_page._import_images()
        qapp.processEvents()

    infos = [
        r.getMessage() for r in caplog.records if r.levelno == logging.INFO
    ]
    assert any("导入完成" in m for m in infos), f"缺导入完成日志，实际：{infos}"


@pytest.mark.unit
def test_split_completion_logged(
    dm_page, fake_threads, monkeypatch, qapp, caplog
):
    """P2-19 RED：数据集划分完成须 logger.info 留痕。"""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )

    with caplog.at_level(logging.INFO, logger="gui.pages.data_manage.page"):
        dm_page._split_dataset()  # 默认比例 0.8/0.1/0.1，和为 1.0
        qapp.processEvents()

    infos = [
        r.getMessage() for r in caplog.records if r.levelno == logging.INFO
    ]
    assert any("划分完成" in m for m in infos), f"缺划分完成日志，实际：{infos}"


@pytest.mark.unit
def test_eval_start_and_complete_logged(
    qapp, fake_threads, monkeypatch, tmp_path, caplog
):
    """P2-19 RED：评估开始/完成各一条 INFO（引擎回退 GT 自比较路径）。"""
    from gui.pages.eval_.page import EvalPage
    import models.supervised.registry as reg_mod

    gt = tmp_path / "gt"
    gt.mkdir()
    for i in range(6):
        _labelme(gt / f"{i}.json", f"{i}.png")
    monkeypatch.setattr(
        reg_mod, "get_engine", lambda enum_val: (_ for _ in ()).throw(
            RuntimeError("no engine"))
    )

    page = EvalPage()
    page._model_edit.setText("fake.pt")
    page._gt_edit.setText(str(gt))
    with caplog.at_level(logging.INFO, logger="gui.pages.eval_.page"):
        page._run_eval()
        qapp.processEvents()

    infos = [
        r.getMessage() for r in caplog.records if r.levelno == logging.INFO
    ]
    assert any("评估开始" in m for m in infos), f"缺评估开始日志，实际：{infos}"
    assert any("评估完成" in m for m in infos), f"缺评估完成日志，实际：{infos}"


@pytest.mark.unit
def test_flawgen_start_and_complete_logged(
    qapp, fake_threads, monkeypatch, tmp_path, caplog
):
    """P2-19 RED：缺陷生成开始/完成各一条 INFO（SGAN 引擎注入路径）。"""
    from core.interfaces_supervised import DetectionResult, TaskType
    from gui.pages.flaw_gen.page import FlawGenPage
    import models.supervised.registry as reg_mod

    ok_dir = tmp_path / "ok"
    flaw_dir = tmp_path / "flaws"
    out_dir = tmp_path / "out"
    ok_dir.mkdir()
    flaw_dir.mkdir()
    _png(ok_dir / "tpl.png")

    class _Sgan:
        def load(self, flaw_database, device="cpu"):
            pass

        def infer(self, p):
            return DetectionResult(
                task=TaskType.SGAN, score=1.0,
                extra={"synthesized_image": np.full((8, 8, 3), 128, np.uint8)},
            )

    monkeypatch.setattr(reg_mod, "get_engine", lambda t: _Sgan())

    page = FlawGenPage()
    page._ok_edit.setText(str(ok_dir))
    page._flaw_edit.setText(str(flaw_dir))
    page._out_edit.setText(str(out_dir))
    page._count_spin.setValue(3)
    with caplog.at_level(logging.INFO, logger="gui.pages.flaw_gen.page"):
        page._start_generate()
        qapp.processEvents()

    infos = [
        r.getMessage() for r in caplog.records if r.levelno == logging.INFO
    ]
    assert any("生成开始" in m for m in infos), f"缺生成开始日志，实际：{infos}"
    assert any("生成完成" in m for m in infos), f"缺生成完成日志，实际：{infos}"
