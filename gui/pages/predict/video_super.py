"""逐帧视频超分 worker（W34 · 零新依赖）。

VideoCapture 逐帧 → super 引擎 infer → extra["hr_image"] → VideoWriter
mp4v。帧数保持（插帧明确 non-goal——RIFE 系重依赖已拒）；输出分辨率随
引擎倍数；输出位置共享约定：{root}/results/superres_{ts}/。
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from project.paths import resolve_base_root

logger = logging.getLogger(__name__)


def superres_save_dir(project_dir: str | None) -> str:
    """视频超分输出目录：{root}/results/superres_{ts}（共享约定）。"""
    ts = int(time.time())
    root = project_dir or resolve_base_root()
    return os.path.join(root, "results", f"superres_{ts}")


def super_video(
    input_path: str,
    output_path: str,
    engine,
    *,
    cancel=None,
    progress_cb: Callable[[int], None] | None = None,
) -> dict:
    """逐帧超分视频。

    Returns:
        {"frames_in", "frames_out", "size_in": (w,h), "size_out": (w,h)}
    Raises:
        ValueError: 输入打不开 / 引擎未返回 hr_image。
    """
    import cv2

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {input_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames_in = frames_out = 0
    writer = None
    out_size = (0, 0)
    try:
        while True:
            if cancel is not None and cancel.is_set():
                break
            ok, frame = cap.read()
            if not ok:
                break
            frames_in += 1
            result = engine.infer(frame)
            hr = (getattr(result, "extra", None) or {}).get("hr_image")
            if hr is None:
                raise ValueError("super 引擎未返回 hr_image（先加载超分权重）")
            if writer is None:
                out_size = (int(hr.shape[1]), int(hr.shape[0]))
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                writer = cv2.VideoWriter(
                    output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, out_size
                )
            writer.write(hr)
            frames_out += 1
            if progress_cb is not None:
                progress_cb(frames_in)
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    logger.info(
        "视频超分完成: %d/%d 帧 %dx%d→%dx%d → %s",
        frames_out, frames_in, w, h, out_size[0], out_size[1], output_path,
    )
    return {
        "frames_in": frames_in,
        "frames_out": frames_out,
        "size_in": (w, h),
        "size_out": out_size,
    }
