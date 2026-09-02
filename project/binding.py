"""工程参数绑定（W58-A——FR-005 对标 SKolpha .spro 工程参数段）。

对标 .spro schema 的 predictionParams{modelFile, threshold} /
transferType{Rect|Polygon} / dataPath 三段——AVA 以项目目录内**明文**
binding.json 承载（SKolpha 的 Fernet 硬编码密钥加密为反面教材，
docs/skolpha-forensics-wave1.md §5）。

- 读侧容错：文件缺失/损坏/非字典/字段类型不符 → 全默认或逐字段丢弃
  （旧工程零破坏；W24 sweep 教训——启动链上的读取必须形状收口）
- 写侧原子：同目录 temp + os.replace
- transfer_type 取值 "Rect"|"Polygon"（SKolpha 原值口径，联动标注默认形态）
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path

from core.interfaces_supervised import TaskType

_logger = logging.getLogger(__name__)

BINDING_FILENAME = "binding.json"
_VALID_TRANSFER_TYPES = ("Rect", "Polygon")
_POLYGON_TASKS = (TaskType.SEG, TaskType.PSEG, TaskType.SSEG)


@dataclass(frozen=True)
class ProjectBinding:
    """项目参数绑定（.spro 三段的 AVA 明文等价物）。"""

    model_file: str = ""            # predictionParams.modelFile
    threshold: float | None = None  # predictionParams.threshold（None=不覆盖 UI）
    transfer_type: str | None = None  # "Rect" | "Polygon"（联动 label 默认形态）
    data_path: str = ""             # 项目数据目录记忆


def binding_path(project_root: str | Path) -> Path:
    """binding.json 路径（不保证存在）。"""
    return Path(project_root) / BINDING_FILENAME


def default_transfer_type(task: TaskType) -> str:
    """任务 → 默认标注形态（SKolpha 语义：分割系 Polygon、检测系 Rect）。"""
    return "Polygon" if task in _POLYGON_TASKS else "Rect"


def read_binding(project_root: str | Path) -> ProjectBinding:
    """读取项目绑定；任何读取层异常 → 全默认（旧工程零破坏）。"""
    path = binding_path(project_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ProjectBinding()
    except (OSError, json.JSONDecodeError):
        _logger.warning("项目绑定读取失败（按默认处理）: %s", path, exc_info=True)
        return ProjectBinding()
    if not isinstance(raw, dict):
        _logger.warning("项目绑定非字典结构（按默认处理）: %s", path)
        return ProjectBinding()

    model_file = raw.get("model_file")
    threshold = raw.get("threshold")
    transfer_type = raw.get("transfer_type")
    data_path = raw.get("data_path")

    if transfer_type not in _VALID_TRANSFER_TYPES:
        if transfer_type is not None:
            _logger.warning("transferType 取值无效，忽略: %r", transfer_type)
        transfer_type = None

    return ProjectBinding(
        model_file=str(model_file) if isinstance(model_file, str) else "",
        threshold=float(threshold) if isinstance(threshold, (int, float)) else None,
        transfer_type=transfer_type,
        data_path=str(data_path) if isinstance(data_path, str) else "",
    )


def write_binding(project_root: str | Path, binding: ProjectBinding) -> None:
    """原子写入项目绑定（mkstemp + os.replace；失败上抛 OSError 由调用方处理）。

    复核 LOW 修正：临时文件用 mkstemp 随机名（固定 .tmp 名在并发
    create_project/update_binding 下互踩——batch_tools.atomic_write_json
    已论证并升为全仓单源纪律，此处对齐）。
    """
    import tempfile

    path = binding_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_file": binding.model_file,
        "threshold": binding.threshold,
        "transfer_type": binding.transfer_type,
        "data_path": binding.data_path,
    }
    fd, tmp = tempfile.mkstemp(
        prefix="binding.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            _logger.warning("绑定临时文件清理失败: %s", tmp, exc_info=True)
        raise


def update_binding(
    project_root: str | Path, **changes: object
) -> ProjectBinding:
    """读改写便捷入口（保留未列出字段；返回更新后的绑定）。"""
    current = read_binding(project_root)
    updated = replace(current, **changes)  # type: ignore[arg-type]
    write_binding(project_root, updated)
    return updated


__all__ = [
    "BINDING_FILENAME",
    "ProjectBinding",
    "binding_path",
    "default_transfer_type",
    "read_binding",
    "update_binding",
    "write_binding",
]
