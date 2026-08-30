"""W34（W26 计划 P2）：逐帧视频超分——VideoCapture → super 引擎 → mp4v。

零新依赖（cv2 自带）；帧数保持（插帧明确 non-goal）；分辨率按引擎倍数
放大；progress 回调单调。输出共享约定：{root}/results/superres_{ts}/。
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_video(path: Path, n: int = 10, w: int = 64, h: int = 64) -> None:
    import cv2

    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h)
    )
    assert writer.isOpened(), "mp4v 后端应可用（opencv 自带 ffmpeg）"
    for i in range(n):
        frame = np.full((h, w, 3), i * 25 % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


class _X2Engine:
    """假超分引擎：2 倍最近邻放大（真引擎语义接口：extra['hr_image']）。"""

    def infer(self, frame, threshold=0.5, labels=None):
        from core.interfaces_supervised import DetectionResult, TaskType

        hr = np.repeat(np.repeat(frame, 2, axis=0), 2, axis=1)
        result = DetectionResult(
            task=TaskType.SUPER, score=1.0, labels=("super_resolved",)
        )
        return result.with_extra("hr_image", hr)


# ============================== 1. Worker 纯函数 ============================== #


@pytest.mark.unit
def test_super_video_frames_preserved_and_upscaled(tmp_path):
    """10 帧入=10 帧出；64→128；进度回调单调递增。"""
    from gui.pages.predict.video_super import super_video

    src = tmp_path / "in.mp4"
    _make_video(src)
    dst = tmp_path / "out.mp4"
    progress = []
    stats = super_video(str(src), str(dst), _X2Engine(), progress_cb=progress.append)

    assert stats["frames_in"] == 10 and stats["frames_out"] == 10
    assert stats["size_in"] == (64, 64) and stats["size_out"] == (128, 128)
    assert dst.stat().st_size > 0
    assert progress == sorted(progress) and len(progress) == 10

    import cv2

    cap = cv2.VideoCapture(str(dst))
    ok, frame = cap.read()
    cap.release()
    assert ok and frame.shape[:2] == (128, 128), "输出帧应 128x128"


@pytest.mark.unit
def test_super_video_cancel_stops_early(tmp_path):
    """取消停帧：已写帧保留、frames_out < frames_in、不炸。"""
    from gui.pages.predict.video_super import super_video

    src = tmp_path / "in.mp4"
    _make_video(src)
    cancel = threading.Event()
    calls = []

    engine = _X2Engine()
    _orig = engine.infer

    def _infer(frame, threshold=0.5, labels=None):
        result = _orig(frame, threshold, labels)
        calls.append(1)
        if len(calls) >= 3:
            cancel.set()
        return result

    engine.infer = _infer
    stats = super_video(str(src), str(tmp_path / "out.mp4"), engine, cancel=cancel)
    assert stats["frames_out"] == 3, f"应停在第 3 帧, got {stats}"


@pytest.mark.unit
def test_super_video_bad_input_raises(tmp_path):
    """打不开的输入 → 明确异常（不静默产出空文件）。"""
    from gui.pages.predict.video_super import super_video

    with pytest.raises((ValueError, OSError)):
        super_video(str(tmp_path / "no_such.mp4"), str(tmp_path / "o.mp4"), _X2Engine())


# ============================== 2. 页面接线 ============================== #


@pytest.mark.unit
def test_video_super_wired(qapp, fake_threads, monkeypatch, tmp_path):
    """推理页视频超分按钮在场：SUPER 引擎 + 选视频 → 产物 mp4 + 状态反馈。"""
    from core.interfaces_supervised import TaskType
    from gui.pages.predict.page import PredictPage

    src = tmp_path / "in.mp4"
    _make_video(src, n=4)

    page = PredictPage()
    page._engine = _X2Engine()
    page._project_dir = str(tmp_path)
    page.cmb_task.setCurrentIndex(
        max(i for i in range(page.cmb_task.count())
            if page.cmb_task.itemData(i) is TaskType.SUPER)
    )
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    # W27 接缝教训：_video_super 在 Mixin（video_super_actions）内解析
    # pick_open_file——补丁须指 Mixin 模块而非页面模块
    from gui.pages.predict import video_super_actions as vsa

    monkeypatch.setattr(vsa, "pick_open_file", lambda *a, **k: str(src))
    from gui.pages.predict import video_super as vs

    monkeypatch.setattr(vs, "resolve_base_root", lambda: str(tmp_path / "ws"))

    assert hasattr(page, "btn_video_super"), "推理页应有视频超分按钮"
    page._video_super()
    qapp.processEvents()

    outs = list(tmp_path.rglob("superres_*/*.mp4"))
    assert outs, f"应产出超分视频, statuses={msgs}"
    assert any("视频超分" in t for t, _ in msgs), msgs
    assert page.btn_video_super.isEnabled()


@pytest.mark.unit
def test_video_super_requires_super_task(qapp, monkeypatch, tmp_path):
    """非 SUPER 任务 → 诚实提示不派发。"""
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    page._engine = _X2Engine()
    page.cmb_task.setCurrentIndex(0)  # DET
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    monkeypatch.setattr(
        "gui.widgets.file_dialog.pick_open_file", lambda *a, **k: "x.mp4"
    )

    page._video_super()
    assert any("超分辨率" in t or "超分" in a for t, a in msgs), msgs


# ============================== 3. permissions ============================== #


@pytest.mark.unit
def test_video_super_action_registered():
    from gui.core.permissions import ROLES, action_allowed

    for role in ROLES:
        assert action_allowed(role, "predict.video_super") is True, role
