"""API 推理源动作 Mixin（W59-A FR-007——页面 ≤800 行守卫，动作外置）。

对标 SKolpha deploymentParams{endpoint, apiKey} 的 API 部署推理形态：
endpoint 输入 + 「API 推理」按钮（单张）——完成链复用 _single_done
（预览/结果行/审计/历史零重复）。密钥经 resolve_api_key（env > 凭据
文件），异常文案零密钥回显。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QLineEdit, QPushButton

from core.exceptions import ApiInferError
from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_open_file

logger = logging.getLogger(__name__)


class ApiInferActionsMixin:
    """远端 API 推理源（endpoint 输入 + 单张 API 推理；无状态）。"""

    def _add_api_source(self, h, bar) -> None:
        """向工具栏布局 h 追加 API 推理源控件（页面 _build_ui 一行挂接）。"""
        self.edit_api_endpoint = QLineEdit(bar)
        self.edit_api_endpoint.setObjectName("apiEndpointEdit")
        self.edit_api_endpoint.setPlaceholderText(tr("API endpoint（http://…）"))
        self.edit_api_endpoint.setFixedWidth(180)
        h.addWidget(self.edit_api_endpoint)

        self.btn_api_infer = QPushButton(tr("API 推理"), bar)
        self.btn_api_infer.setProperty("tool", True)
        self.btn_api_infer.clicked.connect(self._api_infer)
        h.addWidget(self.btn_api_infer)

    def _api_infer(self) -> None:
        """单张远端 API 推理（完成链复用 _single_done：预览/行/审计）。"""
        endpoint = self.edit_api_endpoint.text().strip()
        if not endpoint.lower().startswith(("http://", "https://")):
            self.status_changed.emit(
                tr("请输入有效 endpoint"), tr("须以 http:// 或 https:// 开头")
            )
            return
        # 复核 LOW 修正：与单张推理互斥（共享 _pending_single，两路并发
        # 会互相覆盖结果）——单张进行中时诚实拒绝
        if not self.btn_single.isEnabled():
            self.status_changed.emit(
                tr("推理进行中"), tr("请等待当前推理完成")
            )
            return
        path = pick_open_file(
            self, "选择图像",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if not path:
            return

        self.btn_api_infer.setEnabled(False)
        self.btn_api_infer.setText(tr("推理中..."))
        self.btn_single.setEnabled(False)  # 反向互斥（单张入口见此状态）

        def _work():
            # 调用期导入——monkeypatch 接缝（与页面引擎路径同惯例）
            from inference.api_client import infer_remote, resolve_api_key

            try:
                result = infer_remote(endpoint, path, api_key=resolve_api_key())
                score = float(result.score) if result.score else 0.0
                self._pending_single = (path, result)
                invoke_main(self, "_api_done", os.path.basename(path), score)
            except ApiInferError as exc:
                logger.warning("API 推理失败: %s", exc.endpoint)
                invoke_main(self, "_api_failed", str(exc)[:60])
            except (OSError, RuntimeError, ValueError) as exc:
                invoke_main(self, "_api_failed", str(exc)[:60])

        run_job(
            _work, name="predict_api",
            on_error=ui_on_error(self, "_api_failed"),
        )

    @Slot(str, float)
    def _api_done(self, basename: str, score: float) -> None:
        """槽：API 推理完成（主线程）——复位按钮并复用单张完成链。"""
        self.btn_api_infer.setEnabled(True)
        self.btn_api_infer.setText(tr("API 推理"))
        self.btn_single.setEnabled(True)
        self._single_done(basename, score)

    @Slot(str)
    def _api_failed(self, err: str) -> None:
        """槽：API 推理失败（主线程）——复位按钮并诚实报错。"""
        self.btn_api_infer.setEnabled(True)
        self.btn_api_infer.setText(tr("API 推理"))
        self.btn_single.setEnabled(True)
        self.status_changed.emit(tr("API 推理失败"), err[:60])


__all__ = ["ApiInferActionsMixin"]
