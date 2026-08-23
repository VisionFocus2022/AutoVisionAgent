"""视频超分页面动作 Mixin（W34 自 page.py 抽出——规模守卫 800 线）。

四方法原名混入（W27 SamSessionMixin 同款）：invoke_main 槽名派发
（_video_super_progress/_video_super_done/_video_super_failed）经
MRO 命中本 Mixin，页面装配行为不变。

宿主契约：PredictPage 须提供 status_changed 信号、cmb_task（currentData
为 TaskType）、_engine、_project_dir、btn_video_super（按钮接线
_video_super）；worker 函数在同目录 video_super.py。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Slot

from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_open_file
from gui.core.permissions import check_action  # W35：动作门控


class VideoSuperActionsMixin:
    """逐帧视频超分页面动作（仅 SUPER 任务；插帧 non-goal）。"""

    def _video_super(self) -> None:
        """选视频 → super 引擎逐帧 → mp4v（{root}/results/superres_{ts}）。"""
        if not self._engine:
            self.status_changed.emit(tr("请先加载模型"), "!")
            return
        from core.interfaces_supervised import TaskType

        # W39（v6 P3-1）：门控置于按钮入口首行（与 check_action docstring
        # 约定一致——原置于任务类型预检后）
        denied = check_action("predict.video_super")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        if self.cmb_task.currentData() is not TaskType.SUPER:
            self.status_changed.emit(
                tr("视频超分仅支持超分辨率任务"), "!"
            )
            return
        path = pick_open_file(
            self, "选择视频", "Videos (*.mp4 *.avi *.mov *.mkv)"
        )
        if not path:
            return
        from gui.pages.predict import video_super as vs

        save_dir = vs.superres_save_dir(self._project_dir)
        stem = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(save_dir, f"{stem}_sr.mp4")
        self.btn_video_super.setEnabled(False)
        self.status_changed.emit(tr("视频超分中"), os.path.basename(path))

        def _work(cancel):
            def _progress(done: int) -> None:
                invoke_main(self, "_video_super_progress", done)

            stats = vs.super_video(
                path, out_path, self._engine, cancel=cancel,
                progress_cb=_progress,
            )
            invoke_main(
                self, "_video_super_done",
                stats["frames_out"], stats["frames_in"], out_path,
            )

        run_job(
            _work, name="predict_video_super",
            on_error=ui_on_error(self, "_video_super_failed"),
        )

    @Slot(int)
    def _video_super_progress(self, done: int) -> None:
        self.status_changed.emit(tr("视频超分中"), f"{done} {tr('帧')}")

    @Slot(int, int, str)
    def _video_super_done(self, frames: int, total: int, out_path: str) -> None:
        self.btn_video_super.setEnabled(True)
        self.status_changed.emit(
            tr("视频超分完成"), f"{frames}/{total} → {os.path.basename(out_path)}"
        )

    @Slot(str)
    def _video_super_failed(self, err: str) -> None:
        """槽：视频超分异常兜底（W17 on_error）。"""
        self.btn_video_super.setEnabled(True)
        self.status_changed.emit(tr("操作失败"), err[:60])


__all__ = ["VideoSuperActionsMixin"]
