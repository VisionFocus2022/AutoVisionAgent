"""批量推理 runner（W33 自 page._batch_infer 抽出——规模守卫 800/100 双线）。

职责：_work 闭包（协作取消/分批推理/单结果管线）+ 收尾写盘（取消跳写
语义）。页面保留预检、目录选择、UI 状态与全部 @Slot 槽——invoke_main
槽名派发（_batch_set_progress/_batch_done/_batch_add_row_main）与
ui_on_error 兜底（_batch_failed）经页面解析，行为不变（W27 抽取同款）。

overlay_renderer 由页面注入（模块级 render_result 绑定——保测试缝）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from core.exceptions import SupervisedEngineError
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.pages.predict.workers import (
    atomic_write_json,
    filter_result_by_labels,
    save_batch_artifacts,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 16


def run_batch(
    page,
    *,
    engine: Any,
    images: list,
    save_dir: str,
    threshold: float,
    labels_filter: Optional[set],
    save_overlay: bool,
    overlay_renderer: Optional[Callable] = None,
) -> None:
    """启动批量推理 job（行为语义与 W28/W33 版 _batch_infer._work 一致）。"""
    total = len(images)

    def _process(img_path: str, result) -> None:
        """单结果管线：过滤 → 记录/表格行 → 产物（masks/叠加图）。"""
        if labels_filter is not None:
            result = filter_result_by_labels(result, labels_filter)
        page._batch_add_row(img_path, result)
        overlay = None
        if save_overlay and overlay_renderer is not None:
            try:
                from core.image_io import imread_unicode

                img = imread_unicode(img_path)
                if img is not None:
                    overlay = overlay_renderer(img, result)
            except (ImportError, RuntimeError, ValueError):
                logger.warning("叠加图渲染失败（跳过）: %s", img_path, exc_info=True)
        save_batch_artifacts(save_dir, img_path, result, overlay=overlay)

    def _work(cancel):
        # W18（P2-3 退出链补完）：cancel 参数 → run_job 注入注册表 Event
        cancelled = False
        for i in range(0, total, _BATCH_SIZE):
            if page._batch_cancel or cancel.is_set():
                cancelled = True
                break
            batch_paths = images[i:i + _BATCH_SIZE]
            try:
                if hasattr(engine, "infer_batch"):
                    results = engine.infer_batch(batch_paths, threshold=threshold)
                    for img_path, result in zip(batch_paths, results):
                        _process(img_path, result)
                else:
                    from core.image_io import imread_unicode

                    for img_path in batch_paths:
                        if page._batch_cancel or cancel.is_set():
                            cancelled = True
                            break
                        img = imread_unicode(img_path)
                        if img is None:
                            continue
                        result = engine.infer(img, threshold=threshold)
                        _process(img_path, result)
            except (RuntimeError, OSError, ValueError,
                    SupervisedEngineError):
                # W28 审计折入：引擎级异常（坏权重/推理失败）同收——
                # 旧元组漏收会击穿到 on_error 且引擎残留半加载态
                logger.exception(
                    "批量推理失败 (batch %d-%d)", i, i + len(batch_paths)
                )
            # 更新进度
            done = min(i + _BATCH_SIZE, total)
            invoke_main(page, "_batch_set_progress", done, total)

        if cancelled:
            # W28 落盘卫生：取消即跳过 batch_results.json（表内结果可导出）
            logger.info("批量推理已取消（%d/%d），跳过结果落盘",
                        len(page._results), total)
        else:
            # 原子落盘（temp+replace/tmp 清理见 workers.atomic_write_json）；
            # 建目录推迟到真正写盘——取消路径不残留空目录（W28 审计折入）
            os.makedirs(save_dir, exist_ok=True)
            out_path = os.path.join(save_dir, "batch_results.json")
            atomic_write_json(out_path, page._results)

        invoke_main(page, "_batch_done", len(page._results), total, cancelled)

    run_job(_work, name="predict_batch", on_error=ui_on_error(page, "_batch_failed"))


__all__ = ["run_batch"]
