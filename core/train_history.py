"""训练历史存储（W1-2，roadmap Wave1 模型资产）。

JSONL 追加写 + 新者优先读，落 workspace 根（resolve_base_root——
exe 持久、随用户工作区走）。坏行容忍（跳过计数），存储故障不阻塞
训练完成路径（调用方 best-effort）。

纯模块（无 Qt 依赖）：GUI 页面与训练页共用，亦可脚本侧消费。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

HISTORY_FILENAME = "train_history.jsonl"


def history_path() -> str:
    """历史文件路径（workspace 根，单一事实源 resolve_base_root）。"""
    from project.paths import resolve_base_root

    return os.path.join(resolve_base_root(), HISTORY_FILENAME)


def append_record(record: dict[str, Any]) -> None:
    """追加一条训练记录（目录惰性创建；失败抛 OSError 由调用方兜底）。"""
    path = history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_records(limit: int = 200) -> list[dict[str, Any]]:
    """读取历史（新者优先，至多 limit 条）；坏行跳过并 debug 留痕。"""
    path = history_path()
    if not os.path.isfile(path):
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        logger.warning("训练历史读取失败: %s", path, exc_info=True)
        return []
    for line in reversed(lines):  # 新者在文件尾
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                out.append(rec)
        except ValueError:
            logger.debug("训练历史坏行跳过: %r", line[:80])
        if len(out) >= limit:
            break
    return out


__all__ = ["HISTORY_FILENAME", "history_path", "append_record", "read_records",
           "yaml_classes", "record_from_artifact"]

def yaml_classes(data_yaml: str) -> list:
    """data.yaml names（{id: name} 或列表）→ 排序类别表；失败返回 []。"""
    if not data_yaml:
        return []
    try:
        from yaml import safe_load

        with open(data_yaml, encoding="utf-8") as fh:
            names = (safe_load(fh) or {}).get("names") or {}
        if isinstance(names, dict):
            return [str(names[k]) for k in sorted(names, key=lambda x: int(x))]
        if isinstance(names, list):
            return [str(n) for n in names]
    except (OSError, ValueError, TypeError):
        return []
    return []


def record_from_artifact(artifact, n_epochs: int, real: bool) -> dict:
    """训练产物 → 历史记录（W1-2 落账映射，纯函数无 Qt）。"""
    import time as _time

    cfg = getattr(artifact, "config", None)
    metrics = getattr(artifact, "metrics", None) or {}
    weights = str(getattr(artifact, "weights_path", "") or "")
    return {
        "ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "task": artifact.task.value,
        "real": bool(real),
        "epochs_requested": getattr(cfg, "epochs", None),
        "epochs_completed": n_epochs,
        "weights_path": os.path.abspath(weights) if weights else "",
        "data_yaml": str(getattr(cfg, "data_yaml", "") or ""),
        "backbone": getattr(cfg, "backbone", ""),
        "imgsz": getattr(cfg, "img_size", None),
        "classes": yaml_classes(str(getattr(cfg, "data_yaml", "") or "")),
        "best_metric": float(getattr(artifact, "best_metric", 0.0) or 0.0),
        "metrics": {
            k: metrics.get(k) for k in
            ("precision", "recall", "map50") if metrics.get(k) is not None
        },
    }

