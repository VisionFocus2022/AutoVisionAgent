"""W30（W26 计划 P1/P2）：文件夹批量预标注——目录→逐图 DET 推理→LabelMe JSON。

对标 SKolpha saveData（同时承接批量预测+自动标注产物）；现状单图 W 键
×1288 张是最大标注生产力缺口。

复用成熟模式：W27 prelabel worker 语义（注册≠可用，查 loaded）+
predict 批量 worker 的协作取消/原子写；产物位置与 W33 共享约定：
{项目根 or workspace 根}/results/autolabel_{ts}/（镜像 batchPredict，
绝不写进被扫描数据集目录）。
"""
from __future__ import annotations

import base64
import json
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeThread:
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


def _det(n: int = 1) -> DetectionResult:
    return DetectionResult(
        task=TaskType.DET, score=0.9,
        boxes=tuple((1.0, 2.0, 30.0, 20.0) for _ in range(n)),
        labels=("crack",) * n, scores=(0.9,) * n,
    )


def _fake_registry(monkeypatch, engine) -> None:
    import models.supervised.registry as reg_mod

    class _Reg:
        def has(self, t):
            return True

        def get(self, t):
            return engine

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _Reg())


# ============================== 1. Worker 纯函数 ============================== #


@pytest.mark.unit
def test_batch_prelabel_n_images_n_jsons(tmp_path, monkeypatch):
    """N 张图 → N 个 LabelMe JSON + manifest 计数正确。"""
    from gui.pages.label.batch_prelabel import run_batch_prelabel

    imgs = tmp_path / "imgs"
    imgs.mkdir()
    for i in range(3):
        (imgs / f"i{i}.png").write_bytes(PNG_1PX)

    class _Engine:
        def info(self):
            return {"loaded": True}

        def infer(self, img, threshold=0.5, labels=None):
            return _det(2)

    _fake_registry(monkeypatch, _Engine())
    out = tmp_path / "out"
    manifest = run_batch_prelabel([str(p) for p in imgs.glob("*.png")], str(out))

    jsons = sorted(out.glob("*.json"))
    assert len(jsons) == 3 + 1  # 3 标注 + manifest
    data = json.loads((out / "i0.json").read_text("utf-8"))
    assert data["imagePath"].endswith("i0.png")  # 指回源图（不复制图、不污染源目录）
    assert data["imageHeight"] == 1 and data["imageWidth"] == 1
    assert len(data["shapes"]) == 2
    assert data["shapes"][0]["label"] == "crack"
    assert manifest["total"] == 3 and manifest["written"] == 3
    assert manifest["failed"] == [] and manifest["cancelled"] is False


@pytest.mark.unit
def test_batch_prelabel_cancel_stops_at_k(tmp_path, monkeypatch):
    """取消停在第 k 张：已写 JSON 保留，manifest 记 cancelled=True。"""
    from gui.pages.label.batch_prelabel import run_batch_prelabel

    imgs = tmp_path / "imgs"
    imgs.mkdir()
    for i in range(5):
        (imgs / f"i{i}.png").write_bytes(PNG_1PX)

    cancel = threading.Event()
    calls = []

    class _Engine:
        def info(self):
            return {"loaded": True}

        def infer(self, img, threshold=0.5, labels=None):
            calls.append(1)
            if len(calls) >= 2:
                cancel.set()  # 第 2 张推理后用户取消
            return _det(1)

    _fake_registry(monkeypatch, _Engine())
    out = tmp_path / "out"
    manifest = run_batch_prelabel(
        [str(p) for p in imgs.glob("*.png")], str(out), cancel=cancel
    )

    assert manifest["written"] == 2, f"应停在第 2 张, got {manifest}"
    assert manifest["cancelled"] is True
    assert manifest["total"] == 5


@pytest.mark.unit
def test_batch_prelabel_failed_image_skipped_and_recorded(tmp_path, monkeypatch):
    """坏图跳过并记录（不炸整批）；好图照常产出。"""
    from gui.pages.label.batch_prelabel import run_batch_prelabel

    imgs = tmp_path / "imgs"
    imgs.mkdir()
    (imgs / "good.png").write_bytes(PNG_1PX)
    (imgs / "bad.png").write_bytes(b"junk-not-an-image")

    class _Engine:
        def info(self):
            return {"loaded": True}

        def infer(self, img, threshold=0.5, labels=None):
            return _det(1)

    _fake_registry(monkeypatch, _Engine())
    out = tmp_path / "out"
    manifest = run_batch_prelabel(
        [str(imgs / "good.png"), str(imgs / "bad.png")], str(out)
    )

    assert manifest["written"] == 1
    assert [Path(f).name for f in manifest["failed"]] == ["bad.png"]
    assert (out / "good.json").exists(), "标注 JSON 应落 autolabel 目录（不写图旁）"


@pytest.mark.unit
def test_batch_prelabel_requires_loaded_engine(tmp_path, monkeypatch):
    """引擎未加载权重 → 诚实 raise（注册≠可用，W28 语义延续）。"""
    from core.exceptions import SupervisedEngineError
    from gui.pages.label.batch_prelabel import run_batch_prelabel

    class _UnloadedEngine:
        def info(self):
            return {"loaded": False}

    _fake_registry(monkeypatch, _UnloadedEngine())
    with pytest.raises(SupervisedEngineError, match="加载"):
        run_batch_prelabel([], str(tmp_path / "out"))


# ============================== 2. 产物位置约定（与 W33 共享） ============================== #


@pytest.mark.unit
def test_autolabel_save_dir_mirrors_batchpredict_convention(tmp_path, monkeypatch):
    """{root}/results/autolabel_{ts}：项目根优先，无项目回退 workspace——
    绝不写进被扫描数据集目录（W28 卫生约定）。"""
    from gui.pages.label import batch_prelabel as bp

    out = bp.autolabel_save_dir(str(tmp_path / "proj"))
    assert out.startswith(str(tmp_path / "proj"))
    assert "results" in out.replace("\\", "/")
    assert "autolabel_" in out

    monkeypatch.setattr(bp, "resolve_base_root", lambda: str(tmp_path / "ws"))
    out2 = bp.autolabel_save_dir(None)
    assert out2.startswith(str(tmp_path / "ws")), "无项目须回退 workspace 根"


# ============================== 3. permissions 面更新 ============================== #


@pytest.mark.unit
def test_batch_prelabel_action_registered_for_all_roles():
    """W29 permissions 面更新：label.batch_prelabel 三角色允许（页面
    operator 可见，动作不收紧）。"""
    from gui.core.permissions import ROLES, action_allowed

    for role in ROLES:
        assert action_allowed(role, "label.batch_prelabel") is True, role


# ============================== 4. 页面接线 ============================== #


@pytest.mark.unit
def test_label_page_batch_prelabel_wired(qapp, fake_threads, monkeypatch, tmp_path):
    """标注页批量预标注按钮在场并接线：点选目录→后台 job→JSON 产出+状态反馈。"""
    from gui.pages.label import page as label_mod
    from gui.pages.label.page import LabelPage

    imgs = tmp_path / "imgs"
    imgs.mkdir()
    for i in range(2):
        (imgs / f"i{i}.png").write_bytes(PNG_1PX)

    monkeypatch.setattr(label_mod, "det_engine_available", lambda: True)
    monkeypatch.setattr(label_mod, "pick_directory", lambda *a, **k: str(imgs))
    from gui.pages.label import batch_prelabel as bp
    monkeypatch.setattr(bp, "resolve_base_root", lambda: str(tmp_path / "ws"))

    page = LabelPage()
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    class _Engine:
        def info(self):
            return {"loaded": True}

        def infer(self, img, threshold=0.5, labels=None):
            return _det(1)

    _fake_registry(monkeypatch, _Engine())

    assert hasattr(page, "btn_batch_prelabel"), "标注页应有批量预标注按钮"
    page._batch_prelabel()
    qapp.processEvents()

    results = tmp_path / "ws" / "results"
    jsons = list(results.rglob("autolabel_*/*.json"))
    assert len(jsons) >= 3, f"应产出 2 标注+manifest, got {len(jsons)}"
    assert any("批量预标注" in t for t, _ in page._msgs), page._msgs
    assert page.btn_batch_prelabel.isEnabled()


@pytest.mark.unit
def test_label_page_batch_prelabel_preflight_honest(qapp, monkeypatch, tmp_path):
    """引擎不可用 → 状态栏诚实提示，不派发任务。"""
    from gui.pages.label import page as label_mod
    from gui.pages.label.page import LabelPage

    monkeypatch.setattr(label_mod, "det_engine_available", lambda: False)
    page = LabelPage()
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    page._batch_prelabel()
    assert any("AI预标注不可用" in t or "请先" in t for t, _ in page._msgs), (
        f"预检失败应诚实提示, got: {page._msgs}"
    )
