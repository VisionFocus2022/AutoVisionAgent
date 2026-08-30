"""评估页业务流纯函数（W12-R2，架构审查 v2 巨石拆分）。

从 gui/pages/eval_/page.py 的 _run_eval/_work 抽出的无 Qt 依赖业务逻辑：
扫描数据集 → 取引擎 → 逐张推理 → 算指标 → 汇总结果行。
由页面在 worker 线程调用（对照 data_manage/workers.py 纯函数范式）：
进度/警告通过回调上抛，翻译通过 translate 钩子注入（默认恒等）。
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable

Rows = list[tuple[str, str, str]]
Translate = Callable[[str], str]

GEN_IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif")


def _identity(s: str) -> str:
    return s


def scan_images(root: str, exts=GEN_IMG_EXTS) -> list[str]:
    """递归收集 root 下指定后缀（大小写不敏感）的图像路径。"""
    return [
        os.path.join(r, f)
        for r, _, fs in os.walk(root)
        for f in fs
        if f.lower().endswith(exts)
    ]


def scan_labelme_jsons(gt_dir: str) -> list[str]:
    """收集 gt_dir 顶层 LabelMe JSON 标注路径（非目录返回空）。"""
    if not os.path.isdir(gt_dir):
        return []
    return [
        os.path.join(gt_dir, f) for f in os.listdir(gt_dir)
        if f.endswith(".json")
    ]


def read_annotation(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def extract_gt(ann: dict) -> tuple[list[list], list[int]]:
    """从 LabelMe 标注提取矩形框与全零标签（单点矩形补齐为点框）。"""
    shapes = ann.get("shapes", [])
    boxes = [
        [s["points"][0][0], s["points"][0][1],
         s["points"][1][0] if len(s["points"]) > 1 else s["points"][0][0],
         s["points"][1][1] if len(s["points"]) > 1 else s["points"][0][1]]
        for s in shapes if s.get("shape_type") == "rectangle"
    ]
    return boxes, [0] * len(boxes)


def load_eval_engine(
    model: str,
    task_key: str,
    translate: Translate = _identity,
    on_warn: Callable[[str], None] | None = None,
    logger: logging.Logger | None = None,
) -> object | None:
    """按任务类型加载监督式推理引擎；失败回退 None 并回调 on_warn。"""
    logger = logger or logging.getLogger(__name__)
    engine = None
    try:
        from core.interfaces_supervised import TaskType
        from models.supervised.registry import get_engine
        task_to_enum = {
            "det": TaskType.DET,
            "seg": TaskType.SEG,
            "abdet": TaskType.ABDET,
        }
        enum_val = task_to_enum.get(task_key)
        if enum_val:
            engine = get_engine(enum_val)
            engine.load(model, device="cpu")
            logger.info("评估引擎已加载: %s", model)
    except (ImportError, RuntimeError, OSError, FileNotFoundError):
        logger.exception("加载评估引擎失败，回退到 GT 自比较")
        engine = None
        # W1: 假指标路径显式警告（GT 当预测，指标无意义）
        if on_warn is not None:
            on_warn(translate("评估引擎不可用，退化为 GT 自比较（指标仅供参考）"))
    return engine


def _fallback_pred(boxes: list[list], labels: list[int]) -> dict:
    """引擎缺失/失败/无图时回退：GT 当预测（标注为低置信度）。"""
    return {"boxes": boxes, "scores": [0.5] * len(boxes), "labels": labels}


def build_prediction(
    engine: object | None,
    ann: dict,
    gt_dir: str,
    boxes: list[list],
    labels: list[int],
    logger: logging.Logger | None = None,
) -> dict:
    """对单张标注用引擎真实推理生成预测 dict；失败/无图回退 GT。"""
    logger = logger or logging.getLogger(__name__)
    if engine is None:
        return _fallback_pred(boxes, labels)
    img_path = ann.get("imagePath", "")
    if img_path and not os.path.isabs(img_path):
        img_path = os.path.join(gt_dir, img_path)
    if img_path and os.path.exists(img_path):
        try:
            result = engine.infer(img_path)
            # 真引擎 boxes 为 numpy 数组——不得做真值判断（歧义异常）；
            # W23（v4 P3-3）：boxes 同 score 一并 getattr 防御——缺属性的鸭子
            # 引擎与 boxes=None 走同一 GT 回退，不再 AttributeError 逃出元组。
            r_boxes = getattr(result, "boxes", None)
            p_boxes = r_boxes if r_boxes is not None else boxes
            n_pred = len(p_boxes) if p_boxes is not None else 0
            # W17（v3 P1-2）：三数组长度恒等于预测框数 N——旧 labels[:n_pred]
            # 截断在 M≠N 时产生长度失配，det_map 布尔掩码错配抛 IndexError
            # （实证触发集 M>0∧N≠M，含引擎零检出于有 GT 图）。
            # scores 用引擎真实逐框置信度（缺失/不足时回退全局 score 均匀填充）；
            # labels 恒单类 0：GT 提取本就全零（extract_gt 忽略类别字段），
            # 且引擎 defect_N 字符串不得直喂 det_map 整数比较（==0 全 False → mAP 归零）。
            per_scores = tuple(getattr(result, "scores", None) or ())
            if len(per_scores) >= n_pred:
                out_scores = [float(s) for s in per_scores[:n_pred]]
            else:
                # W23（v4 P3-3）：score 裸取防御——缺 .score（AttributeError）与
                # score=None（float(None) TypeError）均逃出 except 元组炸整场评估；
                # 回退 0.0：score=0/数值标量语义不变，None/缺属性按零置信度填充。
                out_scores = [float(getattr(result, "score", None) or 0.0)] * n_pred
            return {
                "boxes": p_boxes,
                "scores": out_scores,
                "labels": [0] * n_pred,
            }
        except (ImportError, RuntimeError, OSError, FileNotFoundError):
            logger.exception("推理失败: %s", img_path)
    return _fallback_pred(boxes, labels)


def report_progress(
    on_progress: Callable[[int], None] | None, idx: int, total: int
) -> None:
    """R5-8: 每 5 个文件或首尾上报进度百分比。"""
    if on_progress is not None and (idx % 5 == 0 or idx == total - 1):
        on_progress(int((idx + 1) / total * 100))


def format_metric_rows(
    results: dict[str, float], translate: Translate = _identity
) -> Rows:
    """把指标 dict 汇总为结果表行；R5-8: NaN/Inf 校验为 N/A。"""
    rows: Rows = []
    for k, v in sorted(results.items()):
        note = translate("平均值") if k in ("mAP", "mIoU", "AUROC") else translate("单类")
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            rows.append((k, "N/A", note))
        else:
            rows.append((k, f"{v:.4f}", note))
    return rows


def run_supervised_eval(
    model: str,
    gt_dir: str,
    task_key: str,
    on_progress: Callable[[int], None] | None = None,
    translate: Translate = _identity,
    on_warn: Callable[[str], None] | None = None,
    logger: logging.Logger | None = None,
) -> Rows:
    """监督式评估主流程：扫 JSON → 取引擎 → 逐张推理 → 算指标 → 汇总。"""
    from evaluation.metrics_supervised import evaluate_supervised

    logger = logger or logging.getLogger(__name__)
    json_files = scan_labelme_jsons(gt_dir)
    if not json_files:
        return [("-", "N/A", translate("无标注数据"))]

    engine = load_eval_engine(model, task_key, translate, on_warn, logger)
    preds_data, gts_data = [], []
    total = len(json_files)
    for idx, jf in enumerate(json_files):
        report_progress(on_progress, idx, total)
        ann = read_annotation(jf)
        boxes, labels = extract_gt(ann)
        gts_data.append({"boxes": boxes, "labels": labels})
        preds_data.append(build_prediction(engine, ann, gt_dir, boxes, labels, logger))

    results = evaluate_supervised(task_key, preds_data, gts_data)
    return format_metric_rows(results, translate)


def run_generative_eval(
    model: str,
    gt_dir: str,
    task_key: str,
    translate: Translate = _identity,
    max_images: int = 20,
) -> Rows:
    """生成式评估（FID/LPIPS）：model 为目录则递归取图，否则视为单文件。

    W18（P3⑥）：样本帽参数化——max_images 默认 20，页侧不传行为不变。
    """
    from evaluation.generative_metrics import fid_score, perceptual_loss

    rows: Rows = []
    gen_imgs = scan_images(model) if os.path.isdir(model) else [model]
    real_imgs = scan_images(gt_dir)
    if task_key == "fid" and gen_imgs and real_imgs:
        val = fid_score(gen_imgs[:max_images], real_imgs[:max_images])
        rows.append(("FID", f"{val:.2f}", translate("生成质量")))
    elif task_key == "lpips" and gen_imgs and real_imgs:
        val = perceptual_loss(gen_imgs[:max_images], real_imgs[:max_images])
        rows.append(("LPIPS", f"{val:.4f}", translate("感知损失")))
    return rows


def run_eval_task(
    model: str,
    gt_dir: str,
    task_key: str,
    on_progress: Callable[[int], None] | None = None,
    translate: Translate = _identity,
    on_warn: Callable[[str], None] | None = None,
    logger: logging.Logger | None = None,
    max_images: int = 20,
) -> Rows:
    """评估任务入口：按 task_key 分发生成式（fid/lpips）或监督式主流程。

    W18（P3⑥）：max_images 透传生成式分支（默认 20，页侧不传行为不变）。
    """
    if task_key in ("fid", "lpips"):
        return run_generative_eval(model, gt_dir, task_key, translate, max_images)
    return run_supervised_eval(
        model, gt_dir, task_key, on_progress, translate, on_warn, logger
    )


__all__ = [
    "scan_images",
    "scan_labelme_jsons",
    "read_annotation",
    "extract_gt",
    "load_eval_engine",
    "build_prediction",
    "report_progress",
    "format_metric_rows",
    "run_supervised_eval",
    "run_generative_eval",
    "run_eval_task",
]
