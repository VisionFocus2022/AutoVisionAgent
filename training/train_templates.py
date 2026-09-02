"""任务级训练模板 loader（W57 Task 5——FR-004 对标 SKolpha TrainConfigs）。

SKolpha 用 Fernet 加密的 mm 系 .py / ultralytics .yaml 模板 + ``my_*``
参数 30+（解密产物见 .workflow/skolpha-replication/decrypted_trainconfigs/）；
AVA 复刻其「任务级默认 + UI 覆盖」的能力面，但模板为**明文 YAML**
（硬编码对称密钥属反面教材，docs/skolpha-forensics-wave1.md §5）。

- 模板文件：``configs/train_templates/{task}_{variant}.yaml``
  （task=TaskType 值；ocr 推理-only 不设模板——W32 口径）
- 容错：坏文件/非法任务码跳过 + WARNING（诚实清单，不中断其余加载）；
  目录缺失 → 空表（UI 回退内置 _TRAIN_PRESETS）
- 未知字段：validate_raw 报告（UI 状态栏告警不中断——加载仍成功）
- 同名 (task, variant) 重复文件：按文件名序后到者覆盖 + WARNING
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from core.interfaces_supervised import AugmentationConfig, TaskType

logger = logging.getLogger(__name__)

REPO_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "configs" / "train_templates"


@dataclass(frozen=True)
class TrainTemplate:
    """单份任务级训练模板（YAML 加载产物）。

    epochs 为 None = 模板不约束轮数（UI 保留用户当前值）；
    其余字段为模板对训练表单的回填默认。
    """

    task: TaskType
    variant: str
    backbone: str = "yolov8n"
    img_size: int = 640
    epochs: int | None = None
    batch_size: int = 8
    lr: float = 0.001
    augmentation: AugmentationConfig = field(default_factory=AugmentationConfig)

# 顶层已知字段（augmentation 子字段 = AugmentationConfig 字段集）
_TOP_KNOWN = {
    "task", "variant", "backbone", "img_size", "epochs", "batch_size", "lr",
    "augmentation",
}
_AUG_KNOWN = {f.name for f in fields(AugmentationConfig)}


def validate_raw(raw: dict) -> list[str]:
    """报告模板字典中的未知字段（顶层键名 + 'augmentation.x' 点路径）。

    已知顶层=task/variant/backbone/img_size/epochs/batch_size/lr/augmentation；
    augmentation 子字段=AugmentationConfig 字段集。返回空列表=全部识别。
    """
    unknown: list[str] = []
    for key in raw:
        if key not in _TOP_KNOWN:
            unknown.append(str(key))
    aug = raw.get("augmentation")
    if isinstance(aug, dict):
        for key in aug:
            if key not in _AUG_KNOWN:
                unknown.append(f"augmentation.{key}")
    return unknown


def _augmentation_from_raw(raw: dict | None) -> AugmentationConfig:
    """augmentation 段 → AugmentationConfig（list→tuple 归一；None=全默认）。"""
    if not isinstance(raw, dict):
        return AugmentationConfig()
    kwargs: dict = {}
    for f in fields(AugmentationConfig):
        if f.name in raw:
            value = raw[f.name]
            if isinstance(value, list):
                value = tuple(value)
            kwargs[f.name] = value
    return AugmentationConfig(**kwargs)


def load_templates(dir_path: str | Path) -> dict[tuple[str, str], TrainTemplate]:
    """加载目录内全部 {task}_{variant}.yaml 模板。

    Returns:
        {(task_value, variant): TrainTemplate}——文件名序（确定性），
        同键后到者覆盖并 WARNING。
    """
    root = Path(dir_path)
    if not root.is_dir():
        return {}
    templates: dict[tuple[str, str], TrainTemplate] = {}
    for path in sorted(root.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            logger.warning("训练模板解析失败（跳过）: %s (%s)", path.name, exc)
            continue
        if not isinstance(raw, dict):
            logger.warning("训练模板非字典结构（跳过）: %s", path.name)
            continue
        unknown = validate_raw(raw)
        if unknown:
            logger.warning(
                "训练模板 %s 含无法识别字段（已忽略）: %s", path.name, unknown
            )
        task_value = str(raw.get("task", ""))
        try:
            task = TaskType(task_value)
        except ValueError:
            logger.warning(
                "训练模板任务码无效（跳过）: %s task=%r", path.name, task_value
            )
            continue
        variant = str(raw.get("variant") or "normal")
        try:
            template = TrainTemplate(
                task=task,
                variant=variant,
                backbone=str(raw.get("backbone") or "yolov8n"),
                img_size=int(raw.get("img_size") or 640),
                epochs=(
                    int(raw["epochs"])
                    if raw.get("epochs") is not None else None
                ),
                batch_size=int(raw.get("batch_size") or 8),
                lr=float(raw.get("lr") or 0.001),
                augmentation=_augmentation_from_raw(raw.get("augmentation")),
            )
        except (TypeError, ValueError) as exc:
            # 复核 HIGH 修正：数值转换纳入逐文件保护——启动链（训练页
            # 构建期同步调用）上坏值文件只跳过告警，不炸应用
            logger.warning(
                "训练模板字段值非法（跳过）: %s (%s)", path.name, exc
            )
            continue
        key = (task_value, variant)
        if key in templates:
            logger.warning("训练模板重复 (task=%s, variant=%s)：后者覆盖 %s",
                           task_value, variant, path.name)
        templates[key] = template
    return templates


__all__ = [
    "REPO_TEMPLATE_DIR",
    "TrainTemplate",
    "load_templates",
    "validate_raw",
]
