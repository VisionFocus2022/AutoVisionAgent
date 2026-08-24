"""SAM 交互式标注会话 Mixin（W27 自 page.py 抽出，W4-T3 / P2-6 原始实现）。

行为保持抽取：五方法原名混入 LabelPage——invoke_main(self, "_sam_warmed")
等槽名派发按字符串在实例上解析，经 MRO 命中本 Mixin，语义不变。

宿主契约（LabelPage 提供）：
  - status_changed: Signal(str, str) —— 状态栏明示
  - controller: AnnotationController —— attach_interactive(adapter, image)
  - _image_path / _sam_adapter / _sam_busy / _pending_sam_image 会话状态
"""
from __future__ import annotations

from PySide6.QtCore import Slot

from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_open_file


class SamSessionMixin:
    """SAM 依赖探测 → 权重加载 → 帧预热 → 注入 InteractiveLabeler 全程接线。"""

    def _ensure_sam(self) -> None:
        """进入交互式模式：依赖检测 + 权重选择/加载 + 注入（状态栏全程明示）。"""
        if getattr(self._sam_adapter, "loaded", False):
            self._warm_sam()
            return

        try:
            import segment_anything  # noqa: F401  仅探测可选依赖
        except ImportError:
            self.status_changed.emit(tr("SAM 未安装"), tr("交互式标注不可用"))
            return

        ckpt = pick_open_file(self, tr("选择 SAM 权重"), "SAM Checkpoint (*.pth)")
        if not ckpt:
            self.status_changed.emit(tr("SAM 未加载权重"), tr("交互式标注不可用"))
            return

        from labeling.sam_adapter import SamAdapter

        adapter = SamAdapter()
        self._sam_busy = True

        def _work():
            # W21：device 走 resolve_device 契约（W19 已接 7 个 torch 引擎，
            # 本处补齐）——cuda 可用透传、不可用回退 cpu（lite exe 安全）
            from models.supervised.device import resolve_device
            err = ""
            try:
                adapter.load(ckpt, device=resolve_device("cuda"))
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                err = str(exc)
            self._sam_adapter = adapter
            self._sam_busy = False
            if err:
                invoke_main(self, "_sam_failed", err)
                return
            invoke_main(self, "_sam_warmed")

        # W17（v3 P2-1）：on_error 兜底（意外异常时 _sam_busy 复位见 _sam_failed）
        run_job(_work, name="label_sam_load", on_error=ui_on_error(self, "_sam_failed"))

    @Slot()
    def _sam_warmed(self) -> None:
        """槽：权重加载完成（主线程）——继续预热当前帧。"""
        self._warm_sam()

    def _warm_sam(self) -> None:
        """worker 预计算当前帧 embedding（点击时命中缓存，UI 不冻结）。"""
        if not self._image_path or self._sam_busy:
            return
        adapter = self._sam_adapter
        image_path = self._image_path
        self._sam_busy = True

        def _work():
            from core.image_io import imread_unicode

            err = ""
            img = imread_unicode(image_path)
            if img is not None:
                try:
                    adapter.set_image(img)
                except (RuntimeError, OSError, ValueError) as exc:
                    err = str(exc)
            self._sam_busy = False
            if img is None or err:
                invoke_main(self, "_sam_failed", err or tr("图像读取失败"))
                return
            self._pending_sam_image = img
            invoke_main(self, "_sam_attach")

        run_job(_work, name="label_sam_warm", on_error=ui_on_error(self, "_sam_failed"))

    @Slot()
    def _sam_attach(self) -> None:
        """槽：预热完成（主线程）——按当前模式注入。

        W44·C：AUTO 模式注入 AMG detector（全图自动分割 + IOU 阈值过滤）；
        其余 SAM 模式（INTERACTIVE/REGION_SAM/SAM_BRUSH）注入 adapter。
        """
        from labeling.base import AnnotationMode

        mode = self.controller.mode
        if mode is AnnotationMode.AUTO:
            label = self.label_input.text().strip() or "defect"
            detector = self._sam_adapter.build_amg_detector(label=label)
            if self.controller.attach_detector(detector, self._pending_sam_image):
                self.status_changed.emit(tr("SAM 已加载"), tr("自动标注就绪"))
            return
        if self.controller.attach_interactive(
            self._sam_adapter, self._pending_sam_image
        ):
            self.status_changed.emit(tr("SAM 已加载"), tr("交互式标注就绪"))

    @Slot(str)
    def _sam_failed(self, err: str) -> None:
        """槽：SAM 加载/预热失败（主线程）——诚实报错。

        W17：顺带复位 _sam_busy——意外异常路径（on_error 兜底）下 worker
        来不及清标志，不复位会永久阻塞后续预热。
        """
        self._sam_busy = False
        self.status_changed.emit(tr("SAM 加载失败"), err[:60])
