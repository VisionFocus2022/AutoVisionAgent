"""批量推理 runner（W33 自 page._batch_infer 抽出——规模守卫 800/100 双线）。

职责：_work 闭包（协作取消/分批推理/单结果管线）+ 收尾写盘（取消跳写
语义）。页面保留预检、目录选择、UI 状态与全部 @Slot 槽——invoke_main
槽名派发（_batch_set_progress/_batch_done/_batch_add_row_main）与
ui_on_error 兜底（_batch_failed）经页面解析，行为不变（W27 抽取同款）。

overlay_renderer 由页面注入（模块级 render_result 绑定——保测试缝）。

W56（FR-003，对标 SKolpha batchPredictThread/batchPredictOnlyOne）：
- mode="batch"（默认）：整批完成后一次性原子落盘——取消即跳写
  （W28 语义不变）。
- mode="incremental"：逐张即时——每张完成即入表，滚动原子落盘
  （每 10 张或 2s 先到），每张完成后重扫目录支持中途增删文件；
  取消/结束时已处理部分保留在盘（与 batch 模式相区分的落盘承诺）。
- concurrency：仅 infer_batch 路径的后处理（叠加渲染/产物写）经
  ThreadPoolExecutor 并行，引擎前向恒串行（同引擎实例不并发推理——
  线程安全口径）；无 infer_batch 的引擎/逐张模式该选项无效。
  落盘前统一按文件名重排（并行完成序 → 稳定 JSON 序）。
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from core.exceptions import SupervisedEngineError
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.pages.predict.workers import (
    atomic_write_json,
    collect_images,
    filter_result_by_labels,
    save_batch_artifacts,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 16
_INCREMENTAL_FLUSH_EVERY = 10
_INCREMENTAL_FLUSH_SECONDS = 2.0
_MAX_CONCURRENCY = 4


@dataclass(frozen=True)
class _BatchCtx:
    """批处理上下文（页面引用 + 不可变参数——模块级函数共用工件）。"""

    page: Any
    engine: Any
    save_dir: str
    threshold: float
    labels_filter: set | None
    save_overlay: bool
    overlay_renderer: Callable | None


def _process(ctx: _BatchCtx, img_path: str, result) -> None:
    """单结果管线：过滤 → 记录/表格行 → 产物（masks/叠加图）。"""
    if ctx.labels_filter is not None:
        result = filter_result_by_labels(result, ctx.labels_filter)
    ctx.page._batch_add_row(img_path, result)
    overlay = None
    if ctx.save_overlay and ctx.overlay_renderer is not None:
        try:
            from core.image_io import imread_unicode

            img = imread_unicode(img_path)
            if img is not None:
                overlay = ctx.overlay_renderer(img, result)
        except (ImportError, RuntimeError, ValueError):
            logger.warning("叠加图渲染失败（跳过）: %s", img_path, exc_info=True)
    save_batch_artifacts(ctx.save_dir, img_path, result, overlay=overlay)


def _sorted_results(ctx: _BatchCtx) -> list:
    """并发完成序 → 文件名序（W56 AC-003：JSON 序稳定）。"""
    return sorted(ctx.page._results, key=lambda r: str(r.get("file", "")))


def _flush(ctx: _BatchCtx) -> None:
    """滚动原子落盘（incremental 模式；batch 模式走收尾一次性写）。"""
    os.makedirs(ctx.save_dir, exist_ok=True)
    atomic_write_json(
        os.path.join(ctx.save_dir, "batch_results.json"), _sorted_results(ctx)
    )


def _cancelled(ctx: _BatchCtx, cancel) -> bool:
    return ctx.page._batch_cancel or cancel.is_set()


def _run_batch_mode(
    ctx: _BatchCtx, images: list, concurrency: int, cancel
) -> None:
    """整批模式（行为语义与 W28/W33 版一致；并发仅后处理层）。"""
    page = ctx.page
    total = len(images)
    cancelled = False
    # 仅 infer_batch 路径后处理并行；串行引擎路径保持逐张即时 _process
    # （W28 语义：首张完成即入表，取消时已完成行保留）
    executor = (
        ThreadPoolExecutor(max_workers=concurrency,
                           thread_name_prefix="batch_post")
        if concurrency > 1 else None
    )
    try:
        for i in range(0, total, _BATCH_SIZE):
            if _cancelled(ctx, cancel):
                cancelled = True
                break
            batch_paths = images[i:i + _BATCH_SIZE]
            try:
                if hasattr(ctx.engine, "infer_batch"):
                    results = ctx.engine.infer_batch(
                        batch_paths, threshold=ctx.threshold
                    )
                    if executor is not None:
                        list(executor.map(
                            lambda pr: _process(ctx, *pr),
                            zip(batch_paths, results, strict=True),
                        ))
                    else:
                        for img_path, result in zip(batch_paths, results,
                                                    strict=True):
                            _process(ctx, img_path, result)
                else:
                    from core.image_io import imread_unicode

                    for img_path in batch_paths:
                        if _cancelled(ctx, cancel):
                            cancelled = True
                            break
                        img = imread_unicode(img_path)
                        if img is None:
                            continue
                        result = ctx.engine.infer(
                            img, threshold=ctx.threshold
                        )
                        _process(ctx, img_path, result)
            except (RuntimeError, OSError, ValueError, SupervisedEngineError):
                # W28 审计折入：引擎级异常（坏权重/推理失败）同收——
                # 旧元组漏收会击穿到 on_error 且引擎残留半加载态
                logger.exception(
                    "批量推理失败 (batch %d-%d)", i, i + len(batch_paths)
                )
            # 更新进度（取消的中断批也上报——与 W28 版一致）
            done = min(i + _BATCH_SIZE, total)
            invoke_main(page, "_batch_set_progress", done, total)
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    if cancelled:
        # W28 落盘卫生：取消即跳过 batch_results.json（表内结果可导出）
        logger.info("批量推理已取消（%d/%d），跳过结果落盘",
                    len(page._results), total)
    else:
        # 原子落盘（temp+replace/tmp 清理见 workers.atomic_write_json）；
        # 建目录推迟到真正写盘——取消路径不残留空目录（W28 审计折入）
        os.makedirs(ctx.save_dir, exist_ok=True)
        atomic_write_json(
            os.path.join(ctx.save_dir, "batch_results.json"),
            _sorted_results(ctx),
        )

    invoke_main(page, "_batch_done", len(page._results), total,
                cancelled, "batch")


def _run_incremental(
    ctx: _BatchCtx, images: list, images_dir: str | None, cancel
) -> None:
    """逐张即时模式：入表即落盘（滚动）+ 目录重扫（中途可增删）。"""
    page = ctx.page
    cancelled = False
    processed: set[str] = set()
    flushed_at_count = 0
    flushed_at_t = time.monotonic()
    while True:
        if _cancelled(ctx, cancel):
            cancelled = True
            break
        # 每张后重扫目录：新文件续跑纳入、已删文件跳过（中途可增删）
        scan = collect_images(images_dir) if images_dir else list(images)
        pending = [
            p for p in scan if p not in processed and os.path.exists(p)
        ]
        if not pending:
            break
        img_path = pending[0]
        try:
            from core.image_io import imread_unicode

            img = imread_unicode(img_path)
            if img is not None:
                result = ctx.engine.infer(img, threshold=ctx.threshold)
                _process(ctx, img_path, result)
        except (RuntimeError, OSError, ValueError, SupervisedEngineError):
            logger.exception("逐张推理失败（跳过）: %s", img_path)
        processed.add(img_path)
        done = len(processed)
        invoke_main(page, "_batch_set_progress", done, max(done, len(scan)))
        now = time.monotonic()
        if (done - flushed_at_count >= _INCREMENTAL_FLUSH_EVERY
                or now - flushed_at_t >= _INCREMENTAL_FLUSH_SECONDS):
            _flush(ctx)
            flushed_at_count = done
            flushed_at_t = now
    # 逐张即时的落盘承诺：正常结束或取消，已处理部分都在盘上
    _flush(ctx)
    if cancelled:
        logger.info("逐张模式已取消（%d 张已落盘）", len(page._results))
    invoke_main(page, "_batch_done", len(page._results), len(processed),
                cancelled, "incremental")


def run_batch(
    page,
    *,
    engine: Any,
    images: list,
    save_dir: str,
    threshold: float,
    labels_filter: set | None,
    save_overlay: bool,
    overlay_renderer: Callable | None = None,
    mode: str = "batch",
    concurrency: int = 1,
    images_dir: str | None = None,
) -> None:
    """启动批量推理 job（batch 模式语义与 W28/W33 版一致）。"""
    concurrency = max(1, min(int(concurrency), _MAX_CONCURRENCY))
    ctx = _BatchCtx(
        page=page, engine=engine, save_dir=save_dir, threshold=threshold,
        labels_filter=labels_filter, save_overlay=save_overlay,
        overlay_renderer=overlay_renderer,
    )

    def _work(cancel):
        if mode == "incremental":
            _run_incremental(ctx, images, images_dir, cancel)
        else:
            _run_batch_mode(ctx, images, concurrency, cancel)

    run_job(_work, name="predict_batch", on_error=ui_on_error(page, "_batch_failed"))


__all__ = ["run_batch"]
