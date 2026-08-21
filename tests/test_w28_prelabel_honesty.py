"""W28（W26 计划 P1）：AI 预标注诚实化——预检语义/异常捕获/零检出反馈。

背景（对标审查三项 UX 信任债，均落在 W27 抽出的 label/workers.py + page.py）：
1. det_engine_available 只查 registry.has（工厂注册）——ultralytics 装了就
   过检，但引擎从未 load 权重，随后 infer 抛 SupervisedEngineError 逃出
   except 元组（AppError 子类，非 RuntimeError）落到泛化 on_error。
2. run_ai_prelabel / 页面 _work 的捕获元组均缺 SupervisedEngineError。
3. _prelabel_done 零检出时无任何状态反馈——按钮恢复但用户零感知
   （W18"无静默路径"教义的漏网之鱼）。
"""
from __future__ import annotations

import base64
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeThread:
    """threading.Thread 替身：同步执行 target（全仓接缝）。"""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ============================== 1. 预检语义 ============================== #


@pytest.mark.unit
def test_det_engine_available_requires_loaded_weights(monkeypatch):
    """预检语义修复：注册 ≠ 可用——须查引擎已加载权重（info.loaded）。

    RED：现实现只查 registry.has，注册即过检，冷启动必在 infer 期炸。
    """
    from gui.pages.label.workers import det_engine_available
    import models.supervised.registry as reg_mod

    class _UnloadedReg:
        def has(self, t):
            return True  # 工厂已注册

        def get(self, t):
            class _UnloadedEngine:
                def info(self):
                    return {"loaded": False}  # 但从未加载权重

            return _UnloadedEngine()

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _UnloadedReg())
    assert det_engine_available() is False, (
        "已注册但未加载权重的引擎不得过检（infer 将抛 SupervisedEngineError）"
    )

    class _LoadedReg:
        def has(self, t):
            return True

        def get(self, t):
            class _LoadedEngine:
                def info(self):
                    return {"loaded": True}

            return _LoadedEngine()

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _LoadedReg())
    assert det_engine_available() is True

    class _NoReg:
        def has(self, t):
            return False

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _NoReg())
    assert det_engine_available() is False


# ============================== 2. 异常捕获 ============================== #


@pytest.mark.unit
def test_run_ai_prelabel_propagates_supervised_engine_error(
    tmp_path, monkeypatch
):
    """审计折入：引擎级失败必须上抛（页面路由失败槽）——不得摊平成
    空列表冒充"零检出"（用户会误信模型没检出缺陷）。"""
    from core.exceptions import SupervisedEngineError
    from gui.pages.label.workers import run_ai_prelabel
    import models.supervised.registry as reg_mod

    img = tmp_path / "img.png"
    img.write_bytes(PNG_1PX)

    def _boom(im):
        raise SupervisedEngineError("推理失败：权重损坏", task="det")

    class _Engine:
        infer = staticmethod(_boom)

        def info(self):
            return {"loaded": True}

    class _Reg:
        def has(self, t):
            return True

        def get(self, t):
            return _Engine()

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _Reg())

    with pytest.raises(SupervisedEngineError, match="权重损坏"):
        run_ai_prelabel(str(img))


@pytest.mark.unit
def test_prelabel_engine_error_routes_to_failed_slot(
    qapp, fake_threads, monkeypatch, tmp_path
):
    """审计折入：页面 _work 收 SupervisedEngineError → _prelabel_failed
    （按钮恢复 + 状态栏报错），而非零检出反馈。"""
    from core.exceptions import SupervisedEngineError
    from gui.pages.label import page as label_mod
    from gui.pages.label.page import LabelPage

    def _boom(path):
        raise SupervisedEngineError("推理失败：权重损坏", task="det")

    monkeypatch.setattr(label_mod, "det_engine_available", lambda: True)
    monkeypatch.setattr(label_mod, "run_ai_prelabel", _boom)

    page = LabelPage()
    page._image_path = str(tmp_path / "a.png")
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    page._ai_prelabel()
    qapp.processEvents()

    assert page.btn_ai_prelabel.isEnabled()
    assert any(t == "操作失败" and "权重损坏" in a for t, a in page._msgs), (
        f"引擎失败应走失败槽并携带原因，got: {page._msgs}"
    )
    assert not any("零检出" in t or "零检出" in a for t, a in page._msgs), (
        "引擎失败不得冒充零检出"
    )


# ============================== 3. 零检出反馈 ============================== #


@pytest.mark.unit
def test_prelabel_zero_count_explicit_feedback(qapp, fake_threads, monkeypatch, tmp_path):
    """零检出必须给显式状态反馈（W18 无静默路径——按钮恢复≠用户知情）。"""
    from gui.pages.label import page as label_mod
    from gui.pages.label.page import LabelPage

    monkeypatch.setattr(label_mod, "det_engine_available", lambda: True)
    monkeypatch.setattr(label_mod, "run_ai_prelabel", lambda p: [])  # 零检出

    page = LabelPage()
    page._image_path = str(tmp_path / "a.png")
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    page._ai_prelabel()
    qapp.processEvents()

    assert page.btn_ai_prelabel.isEnabled()
    zero_feedback = [t for t, _ in page._msgs if "零检出" in t or "零检出" in _]
    assert zero_feedback, (
        f"零检出后状态栏应含显式反馈（含'零检出'），got: {page._msgs}"
    )
