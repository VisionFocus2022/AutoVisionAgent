"""文件夹批量预标注工作函数（W30 · 对标 SKolpha saveData 自动标注产物）。

纯函数层：无 Qt 依赖（invoke_main 状态反馈由页面槽处理），可同步单测。

产物位置约定（与 W33 共享，勿两波各定义）：
  {项目根 or workspace 根}/results/autolabel_{ts}/
  —— 镜像 predict 批量的 batchPredict_{ts} 约定（W28 卫生：无项目回退
  workspace 根，绝不写进被扫描数据集目录）。内容：
  - {图名}.json：LabelMe 标注（imagePath 指回源图，不复制图）
  - manifest.json：{total, written, failed[], cancelled, relpath_fallback[]}（temp+replace 原子写；relpath_fallback=跨盘符回退绝对路径的源图清单，W38·v6 P2-2）

复用成熟模式：W27/W28 预检语义（注册≠可用，查 info()["loaded"]）+
predict 批量 worker 的协作取消（threading.Event）与原子写。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from labeling import AnnotationMode, Shape
from labeling.batch_tools import atomic_write_json  # W39·v6 P2-8：原子写单源
from labeling.io_labelme import save_labelme
from project.paths import resolve_base_root

logger = logging.getLogger(__name__)


def autolabel_save_dir(project_dir: Optional[str]) -> str:
    """批量预标注输出目录：{root}/results/autolabel_{ts}（共享约定）。"""
    ts = int(time.time())
    root = project_dir or resolve_base_root()
    return os.path.join(root, "results", f"autolabel_{ts}")


def _shapes_from_result(result) -> List[Shape]:
    """DetectionResult → Shape 列表（语义同 run_ai_prelabel：框→矩形，
    标签缺省 defect；boxes 为 numpy/元组序列——不做真值判断）。"""
    if result.boxes is None or len(result.boxes) == 0:
        return []
    labels = result.labels or ()
    shapes = []
    for i, box in enumerate(result.boxes):
        label = labels[i] if i < len(labels) else "defect"
        shapes.append(
            Shape(
                AnnotationMode.RECTANGLE,
                ((float(box[0]), float(box[1])),
                 (float(box[2]), float(box[3]))),
                label=label,
            )
        )
    return shapes


def run_batch_prelabel(
    images: List[str],
    out_dir: str,
    *,
    cancel=None,
    threshold: float = 0.5,
) -> Dict:
    """目录内逐图 DET 推理 → LabelMe JSON 写入 autolabel 目录。

    语义：
    - 引擎未加载权重 → SupervisedEngineError（注册≠可用，W28 语义）；
    - 坏图/单图推理失败 → 跳过并记入 manifest.failed（不炸整批）；
    - cancel 置位 → 停在当前图，已写 JSON 保留，manifest 记 cancelled；
    - 零检出不算失败——照样写空 shapes JSON（标记"已处理未检出"）。

    Returns:
        manifest 字典 {total, written, failed, cancelled}。
    """
    from core.exceptions import SupervisedEngineError
    from core.image_io import imread_unicode
    from core.interfaces_supervised import TaskType
    from models.supervised.registry import get_default_registry

    reg = get_default_registry()
    engine = reg.get(TaskType.DET)
    info = engine.info() if hasattr(engine, "info") else {}
    if not info.get("loaded"):
        raise SupervisedEngineError(
            "DET 引擎未加载权重——请先在推理页加载模型", task="det"
        )

    os.makedirs(out_dir, exist_ok=True)
    failed: List[str] = []
    written = 0
    cancelled = False
    cross_drive: List[str] = []  # 跨盘符回退绝对路径的源图（v6 P2-2）

    for image_path in images:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        try:
            img = imread_unicode(image_path)
            if img is None:
                failed.append(image_path)
                logger.warning("批量预标注跳过：图像读取失败 %s", image_path)
                continue
            result = engine.infer(img, threshold=threshold)
            shapes = _shapes_from_result(result)
            h, w = img.shape[:2]
            json_name = Path(image_path).stem + ".json"
            # v5 P3#6：imagePath 相对 JSON 所在目录（LabelMe 生态惯例——
            # 绝对路径在标注目录整体迁移后断链）；v6 P2-2：跨盘符时
            # relpath 抛 ValueError——回退写绝对路径（LabelMe 兼容），
            # 并记入 manifest.relpath_fallback 区分「跨盘回退」与「坏图」
            img_drv, _ = os.path.splitdrive(os.path.abspath(image_path))
            out_drv, _ = os.path.splitdrive(os.path.abspath(out_dir))
            if img_drv.upper() == out_drv.upper():
                image_path_field = os.path.relpath(image_path, out_dir)
            else:
                image_path_field = os.path.abspath(image_path)
                cross_drive.append(image_path)
            save_labelme(
                os.path.join(out_dir, json_name),
                shapes, image_path_field, h, w,
            )
            written += 1
        except (RuntimeError, OSError, ValueError) as exc:
            failed.append(image_path)
            logger.warning("批量预标注失败（跳过）%s: %s", image_path, exc)

    manifest = {
        "total": len(images),
        "written": written,
        "failed": failed,
        "cancelled": cancelled,
        "relpath_fallback": cross_drive,
    }
    atomic_write_json(os.path.join(out_dir, "manifest.json"), manifest)
    logger.info(
        "批量预标注完成: %d/%d written=%d failed=%d cancelled=%s → %s",
        written, len(images), written, len(failed), cancelled, out_dir,
    )
    return manifest
