"""标注页 AI 预标注工作函数（W27 自 page.py 抽出，仿 data_manage/workers.py）。

纯函数层：无 Qt 依赖，可同步单测；由页面在 worker 线程调用。
W28 预标注诚实化修复（预检语义/异常捕获/零检出反馈）落点在本模块。
"""
from __future__ import annotations

import logging
from typing import List

from labeling import AnnotationMode, Shape

logger = logging.getLogger(__name__)


def det_engine_available() -> bool:
    """检查 DET 引擎是否已加载权重（W28 预检语义修复）。

    旧实现只查 registry.has（工厂注册）——ultralytics 装了就过检，但
    引擎从未 load 权重，随后 infer 抛 SupervisedEngineError 逃出页面
    except 元组落到泛化 on_error。现语义：注册 ≠ 可用，须查引擎
    info()["loaded"]（AbstractTaskEngine 以 _model 在场判加载态）。

    副作用说明（审计折入）：reg.get() 会实例化并缓存引擎（构造廉价、
    无 GPU 占用），该缓存实例与 predict 页加载的是同一个——「先在
    predict 页加载 DET 模型、再回标注页预标注」是当前唯一可用路径，
    两者共享 registry 实例缓存是有意耦合，勿拆。
    """
    try:
        from models.supervised.registry import get_default_registry
        from core.interfaces_supervised import TaskType
        reg = get_default_registry()
        if not reg.has(TaskType.DET):
            return False
        engine = reg.get(TaskType.DET)
        info = engine.info() if hasattr(engine, "info") else {}
        return bool(info.get("loaded"))
    except (ImportError, RuntimeError, OSError, ValueError):
        return False


def run_ai_prelabel(image_path: str) -> List:
    """AI 预标注纯工作函数（W3-T3 自 _ai_prelabel 抽出，无 Qt 依赖）。

    registry 直连为 GUI 正式形态（v3 P2-7）：仅用已注册的 DET 引擎推理。
    W18 诚实化：零样本 dispatcher 回退桥已删（零样本未实装，回退必失败）；
    引擎不可用由页面 det_engine_available 预检在状态栏明示，此处仅兜底
    返回空列表并记 WARNING，不留静默路径。
    返回 Shape 列表（可能为空）。
    """
    try:
        # registry 直连为 GUI 正式形态（v3 P2-7）
        from models.supervised.registry import get_default_registry
        from core.interfaces_supervised import TaskType
        reg = get_default_registry()
        if not reg.has(TaskType.DET):
            logger.warning("AI 预标注跳过：无已注册 DET 引擎（零样本未实装）")
            return []
        engine = reg.get(TaskType.DET)
        from core.image_io import imread_unicode
        img = imread_unicode(image_path)
        if img is None:
            logger.warning("AI 预标注跳过：图像读取失败 %s", image_path)
            return []
        result = engine.infer(img)
        # 真引擎 boxes 是 numpy 数组——不得做真值判断（歧义异常，W9 修复）
        if result.boxes is None or len(result.boxes) == 0:
            return []
        # W39（v6 P2-7）：逐框取标签（与 batch_prelabel._shapes_from_result
        # 同语义——原全框共用 labels[0] 属两条预标注路径语义分叉）
        labels = result.labels or ()
        return [
            Shape(
                AnnotationMode.RECTANGLE,
                ((float(box[0]), float(box[1])),
                 (float(box[2]), float(box[3]))),
                label=labels[i] if i < len(labels) else "defect",
            )
            for i, box in enumerate(result.boxes)
        ]
    except (ImportError, RuntimeError, OSError, ValueError):
        # W28 审计折入：SupervisedEngineError（引擎/权重级失败）不在此收编
        # ——上抛由页面 _work 显式路由 _prelabel_failed；「零检出」反馈只
        # 留给真实的零框结果，防止推理失败被冒充成"模型没检出缺陷"
        logger.exception("AI 预标注失败")
        return []
