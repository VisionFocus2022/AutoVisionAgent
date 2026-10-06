"""SAM 交互式标注会话 Mixin（W27 自 page.py 抽出，W4-T3 / P2-6 原始实现）。

行为保持抽取：五方法原名混入 LabelPage——invoke_main(self, "_sam_warmed")
等槽名派发按字符串在实例上解析，经 MRO 命中本 Mixin，语义不变。

W46：SAM3 后端装配——AVA_SAM3_DIR 有效目录或对话框选中 config.json
（同目录含 model.safetensors）时走 Sam3Adapter（transformers）；
否则原 SAM1（segment-anything）流程不变。

宿主契约（LabelPage 提供）：
  - status_changed: Signal(str, str) —— 状态栏明示
  - controller: AnnotationController —— attach_interactive(adapter, image)
  - _image_path / _sam_adapter / _sam_state / _pending_sam_image 会话状态
    （_sam_busy 为只读兼容属性 = 非Idle，W56·v7 P2-5）
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Slot

from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_open_file


def resolve_sam3_model_dir(
    env_value: str | None,
    picked_path: str | Path | None,
) -> str | None:
    """SAM3 模型目录解析（纯函数，W46）。

    - AVA_SAM3_DIR 指向含 config.json + model.safetensors 的目录 → 该目录
      （测试/幂等装配优先通道；W57·v7 P3-5 起与对话框分支同口径双文件
      校验——env 指坏目录立即回落，不再延迟一个加载周期才诚实报错）；
    - 对话框选中 config.json 且同目录存在 model.safetensors → 其父目录
      （transformers from_pretrained 目录形态）；
    - 其余（含 .pth 选择、env 目录无效/缺文件）→ None，回落 SAM1 流程。
    """
    if env_value:
        p = Path(env_value)
        if p.is_dir() and (p / "config.json").is_file() \
                and (p / "model.safetensors").is_file():
            return str(p)
    if picked_path is not None and Path(picked_path).name == "config.json":
        parent = Path(picked_path).parent
        if (parent / "model.safetensors").is_file():
            return str(parent)
    return None


class _SamAsyncChannel:
    """labeler → worker 线程推理的受理口（W56·v7 P1-3）。

    submit(fn, tag) -> bool：状态机空闲即受理（独占 predicting，torch
    前向串行）；忙时提示并拒绝。结果经「通道暂存 + invoke_main 原语
    唤起」回投主线程（重对象——logits 张量 / Shape 列表——按引用
    传递，不走 QVariant 载荷；thread_bridge 认可的页面暂存模式）。
    """

    def __init__(self, page) -> None:
        self._page = page
        self.pending: tuple | None = None   # (tag, err, result)
        self.ctx: tuple | None = None       # (submit 时 labeler, image)

    def submit(self, fn, tag: str) -> bool:
        page = self._page
        if page._sam_state != page._SAM_IDLE:
            page.status_changed.emit(tr("SAM 处理中"), tr("请稍候"))
            return False
        page._sam_set_state(page._SAM_PREDICTING)
        labeler = page.controller._labeler
        self.ctx = (labeler, getattr(labeler, "_image", None))
        page.status_changed.emit(
            tr("自动分割中") if tag == "auto" else tr("推理中"), ""
        )

        def _work(cancel=None):
            err = ""
            result = None
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 — 路由点，须全收
                import logging as _log

                _log.getLogger(__name__).exception("SAM 推理失败（worker）")
                err = str(exc)
            self.pending = (tag, err, result)
            invoke_main(page, "_sam_predict_ready")

        run_job(
            _work, name="label_sam_predict",
            on_error=ui_on_error(page, "_sam_failed"),
        )
        return True


class SamSessionMixin:
    """SAM 依赖探测 → 权重加载 → 帧预热 → 注入 InteractiveLabeler 全程接线。"""

    # ============================== 状态机（W56·v7 P2-5） ============================== #
    # idle → loading（权重加载）→ idle → warming（帧预热）→ idle →
    # predicting（推理，W56·v7 P1-3）→ idle；任一非 idle 态拒绝新任务——
    # torch 前向非线程安全语义下的全链串行（原 _sam_busy 布尔仅覆盖
    # loading/warming 两态，且 _ensure_sam 顶部无守卫可双发加载 job）。
    _SAM_IDLE = "idle"
    _SAM_LOADING = "loading"
    _SAM_WARMING = "warming"
    _SAM_PREDICTING = "predicting"

    @property
    def _sam_busy(self) -> bool:
        """兼容视图：非 idle 即忙（旧调用方/测试契约保持）。"""
        return self._sam_state != self._SAM_IDLE

    def _sam_set_state(self, state: str) -> None:
        """状态迁移（O7·契约 C4，2026-10-05 二轮审查）。

        状态机迁移收敛主线程：worker 线程调用时经 invoke_main 排队
        （QueuedConnection 顺序保证 = 迁移与 worker 后续回调同序），
        主线程调用时立即执行。此前 worker 直接写 _sam_state——str 赋值
        GIL 原子无数据撕裂，但与主线程守卫的时序契约脆弱（守卫通过与
        迁移执行之间无屏障）。
        """
        import threading

        if threading.current_thread() is not threading.main_thread():
            invoke_main(self, "_sam_set_state_main", state)
        else:
            self._sam_state = state

    @Slot(str)
    def _sam_set_state_main(self, state: str) -> None:
        """槽：状态迁移（主线程执行，O7·契约 C4）。"""
        self._sam_state = state

    def _ensure_sam(self) -> None:
        """进入交互式模式：依赖检测 + 权重选择/加载 + 注入（状态栏全程明示）。

        W46：AVA_SAM3_DIR 有效目录优先走 SAM3；对话框选中 config.json
        （同目录含 model.safetensors）亦走 SAM3；其余回落 SAM1 原流程。
        W56·v7 P2-5：顶部重入守卫——加载/预热/推理在途时拒绝再入（原
        无守卫，加载在途再触发会双发加载 job 且后发覆盖 _sam_adapter）。
        """
        if self._sam_state != self._SAM_IDLE:
            self.status_changed.emit(tr("SAM 处理中"), tr("请稍候"))
            return
        if getattr(self.controller, "_async_channel", None) is None:
            # W56·v7 P1-3：异步推理通道惰性接线（page.py 零增行约束）
            self.controller.set_async_channel(_SamAsyncChannel(self))
        if getattr(self._sam_adapter, "loaded", False):
            self._warm_sam()
            return

        sam3_dir = resolve_sam3_model_dir(os.environ.get("AVA_SAM3_DIR"), None)
        if sam3_dir:
            self._load_sam3(sam3_dir)
            return

        try:
            import segment_anything  # noqa: F401  仅探测可选依赖
        except ImportError:
            self.status_changed.emit(tr("SAM 未安装"), tr("交互式标注不可用"))
            return

        ckpt = pick_open_file(
            self, tr("选择 SAM 权重"),
            "SAM Checkpoint (*.pth);;SAM3 Model (config.json)",
        )
        if not ckpt:
            self.status_changed.emit(tr("SAM 未加载权重"), tr("交互式标注不可用"))
            return

        sam3_dir = resolve_sam3_model_dir(None, Path(ckpt))
        if sam3_dir:
            self._load_sam3(sam3_dir)
            return

        from labeling.sam_adapter import SamAdapter

        adapter = SamAdapter()
        self._sam_set_state(self._SAM_LOADING)

        def _work():
            # W21：device 走 resolve_device 契约（W19 已接 7 个 torch 引擎，
            # 本处补齐）——cuda 可用透传、不可用回退 cpu（lite exe 安全）
            # O7·契约 C2 模式②：adapter 经 pending 属性 + invoke_main 由
            # 主线程槽赋值（worker 不再直接写 self._sam_adapter）
            from models.supervised.device import resolve_device
            err = ""
            try:
                adapter.load(ckpt, device=resolve_device("cuda"))
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                err = str(exc)
            self._pending_sam_adapter = adapter
            self._sam_set_state(self._SAM_IDLE)
            if err:
                invoke_main(self, "_sam_failed", err)
                return
            invoke_main(self, "_sam_warmed")

        # W17（v3 P2-1）：on_error 兜底（意外异常时 _sam_busy 复位见 _sam_failed）
        run_job(_work, name="label_sam_load", on_error=ui_on_error(self, "_sam_failed"))

    def _load_sam3(self, model_dir: str) -> None:
        """W46：SAM3 后端加载（transformers 目录形态）——异步，模式同上。"""
        try:
            from labeling.sam3_adapter import Sam3Adapter
        except ImportError as exc:
            # exe 冻结态若未打包 sam3_adapter/transformers（函数级导入对
            # PyInstaller 静态分析不可见，W16 同款）——诚实报错不裸穿 Qt 槽
            self.status_changed.emit(
                tr("SAM 未安装"), f"SAM3 模块不可用: {exc}"[:60]
            )
            return

        adapter = Sam3Adapter()
        # W57·v7 P3-6：后端能力差异一次性明示（诚实降级感知通道）
        self.status_changed.emit(
            tr("提示"), tr("SAM3 后端不支持负点击与笔刷迭代精修")
        )
        self._sam_set_state(self._SAM_LOADING)

        def _work():
            # O7·契约 C2 模式②：同 SAM1 路径——adapter 经 pending 属性
            # 由主线程槽赋值
            from models.supervised.device import resolve_device
            err = ""
            try:
                adapter.load(model_dir, device=resolve_device("cuda"))
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                err = str(exc)
            self._pending_sam_adapter = adapter
            self._sam_set_state(self._SAM_IDLE)
            if err:
                invoke_main(self, "_sam_failed", err)
                return
            invoke_main(self, "_sam_warmed")

        run_job(
            _work, name="label_sam3_load", on_error=ui_on_error(self, "_sam_failed")
        )

    @Slot()
    def _sam_warmed(self) -> None:
        """槽：权重加载完成（主线程）——消费 pending adapter（O7·契约 C2
        模式②）后继续预热当前帧。"""
        pending = getattr(self, "_pending_sam_adapter", None)
        if pending is not None:
            self._sam_adapter = pending  # 主线程赋值（契约 C4）
            self._pending_sam_adapter = None
        self._warm_sam()

    def _warm_sam(self) -> None:
        """worker 预计算当前帧 embedding（点击时命中缓存，UI 不冻结）。"""
        if not self._image_path or self._sam_state != self._SAM_IDLE:
            return
        adapter = self._sam_adapter
        image_path = self._image_path
        self._sam_set_state(self._SAM_WARMING)

        def _work():
            from core.image_io import imread_unicode

            err = ""
            img = imread_unicode(image_path)
            if img is not None:
                try:
                    adapter.set_image(img)
                except (RuntimeError, OSError, ValueError) as exc:
                    err = str(exc)
            self._sam_set_state(self._SAM_IDLE)
            if img is None or err:
                invoke_main(self, "_sam_failed", err or tr("图像读取失败"))
                return
            self._pending_sam_image = img
            # W55·v7 P1-2：携带预热目标路径——_sam_attach 据此识别丢拍
            invoke_main(self, "_sam_attach", image_path)

        run_job(_work, name="label_sam_warm", on_error=ui_on_error(self, "_sam_failed"))

    @Slot(str)
    def _sam_attach(self, warmed_path: str) -> None:
        """槽：预热完成（主线程）——按当前模式注入。

        W44·C：AUTO 模式注入 AMG detector（全图自动分割 + IOU 阈值过滤）；
        其余 SAM 模式（INTERACTIVE/REGION_SAM）注入 adapter。
        W55·v7 P1-2：路径校验防丢拍——预热完成时用户已换图（warmed_path
        与当前 _image_path 不一致）则丢弃本次结果、对当前图重发预热，
        旧图 embedding 不再注入新画布。
        """
        from labeling.base import AnnotationMode

        if warmed_path != self._image_path:
            self._warm_sam()
            return

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

    @Slot()
    def _sam_predict_ready(self) -> None:
        """槽：异步推理完成（主线程）——陈旧性校验后回投 labeler（P1-3）。

        陈旧双校验（W55/W56 联动）：labeler 身份变（模式切换重建）或
        帧引用变（换图失效/重预热注入新帧）即丢弃——旧图推理结果不得
        落到新画布（v7 P1-2 的异步面闭环）。
        """
        channel = getattr(self.controller, "_async_channel", None)
        if channel is None or channel.pending is None:
            return
        tag, err, result = channel.pending
        channel.pending = None
        self._sam_set_state(self._SAM_IDLE)
        if err:
            self._on_labeler_feedback("error", f"SAM 推理失败: {err}")
            return
        submit_labeler, submit_image = channel.ctx or (None, None)
        labeler = self.controller._labeler
        if (labeler is not submit_labeler
                or getattr(labeler, "_image", None) is not submit_image):
            return  # 结果过期：换图/换模式路径已自行触发 re-warm
        labeler.deliver(tag, result)
        self.controller.refresh_preview()

    def unload_sam(self) -> None:
        """卸载 SAM 释放显存（W56·v7 P2-1；工具栏动作与 closeEvent 共用）。

        前置：状态机 idle（推理/预热在途时拒绝——防在途竞态）。
        卸载后 _sam_adapter=None、labeler 帧失效，可重新走加载链。
        """
        if self._sam_state != self._SAM_IDLE:
            self.status_changed.emit(tr("SAM 处理中"), tr("请稍候"))
            return
        adapter = self._sam_adapter
        if adapter is None or not getattr(adapter, "loaded", False):
            self.status_changed.emit(tr("提示"), "SAM 未加载，无需卸载")
            return
        try:
            adapter.unload()
        except Exception as exc:  # noqa: BLE001 — 卸载失败不炸 UI
            import logging as _log

            _log.getLogger(__name__).exception("SAM 卸载异常")
            self.status_changed.emit(tr("提示"), f"SAM 卸载异常: {exc}"[:60])
            return
        self._sam_adapter = None
        self._pending_sam_image = None
        self.controller.invalidate_image()
        self.status_changed.emit(tr("SAM 已卸载"), "VRAM 已释放（如适用）")

    def closeEvent(self, event) -> None:
        """页面关闭：卸载 SAM 释放显存（W56·v7 P2-1）。

        收尾兜底——任何失败不得改写关闭语义（进程退出本身也会回收）。
        """
        try:
            if (self._sam_state == self._SAM_IDLE
                    and getattr(self._sam_adapter, "loaded", False)):
                self._sam_adapter.unload()
        except Exception:  # noqa: BLE001
            # L5（2026-10-05 二轮审查）：兜底吞异常须留痕（全仓约定），
            # 不改写关闭语义（debug 级——进程退出本身也会回收显存）。
            import logging

            logging.getLogger(__name__).debug(
                "closeEvent SAM 卸载兜底失败", exc_info=True
            )
        super().closeEvent(event)

    def _on_labeler_feedback(self, kind: str, msg: str) -> None:
        """标注器反馈 → 状态栏（W55·v7 P2-4：操作员感知通道）。

        kind: error 推理失败 / warn 未就绪（未加载或预热中）/
        info 零产出（如 AUTO 未检出目标）。
        """
        titles = {
            "error": tr("推理失败"),
            "warn": tr("SAM 未就绪"),
            "info": tr("提示"),
        }
        self.status_changed.emit(titles.get(kind, tr("提示")), msg[:60])

    def _sync_sam_session(self) -> None:
        """换图 SAM 会话同步（W55·v7 P1-2，全 SAM 模式）。

        ① controller.cancel()：模式会话态重置（RegionSam 区域框）；
        ② controller.invalidate_image()：旧帧引用失效——新图预热完成前
           预测 no-op，新图坐标不进旧图模型；
        ③ _warm_sam()：异步预热新图（在途 busy 时本次跳过，由
           _sam_attach 的路径校验闭环对当前图补发）。

        W4-T3 原仅 INTERACTIVE 生效——W43/W44 新增 REGION_SAM/
        AUTO 两模式未同步扩展，v7 P1-2 收口。
        """
        self.controller.cancel()
        self.controller.invalidate_image()
        self._warm_sam()

    @Slot(str)
    def _sam_failed(self, err: str) -> None:
        """槽：SAM 加载/预热失败（主线程）——诚实报错。

        W17：顺带复位 _sam_busy——意外异常路径（on_error 兜底）下 worker
        来不及清标志，不复位会永久阻塞后续预热。
        """
        self._sam_set_state(self._SAM_IDLE)
        self.status_changed.emit(tr("SAM 加载失败"), err[:60])
