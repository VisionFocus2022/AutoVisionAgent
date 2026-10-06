"""标注批量处理工具（对标 SKolpha frontend.tools）。

3 个纯函数工具（W61：翻转/切割两链路已按用户裁决全链删除）：
1. batch_replace_label — 批量替换标签名
2. label_data_statistics — 标注数据统计（各类别数量/分布）
3. batch_delete_labels — 批量删除标注

另有 atomic_write_json 原子写底座（P2-2 单源，predict/测试复用）。
所有函数纯 I/O，无 Qt 依赖，可独立测试。
所有 JSON 落盘均为原子写（同目录 tmp + os.replace）：写盘中途失败或进程
退出不会截断/损坏既有标注文件（P2-2）。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

from core.exceptions import AppError  # L1（2026-10-06 三轮审查）：AnnotationIOError 基类
from labeling.io_labelme import load_labelme

logger = logging.getLogger(__name__)


def atomic_write_json(path: str, doc: dict[str, Any]) -> None:
    """原子写 JSON：先写同目录临时文件，再 os.replace 替换目标。

    P2-2：直写是 truncate-then-write，写盘中途失败/进程退出会把目标
    JSON 截断且旧内容已丢。本函数保证任何一步失败都不触碰旧文件：

    - 临时文件与目标同目录（同盘，os.replace 原子性前提），mkstemp
      随机名（并发写同一目标不互踩——W39·v6 P2-8：升为全仓单源，
      gui 两处固定 .tmp 名的弱版已删，此处为唯一实现）；
    - 写入参数与直写版一致（utf-8 / ensure_ascii=False / indent=2）；
    - 异常类型与直写版一致上抛（open OSError / dump 原样 / replace OSError），
      上抛前尽力清理残留临时文件。
    """
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
        dir=os.path.dirname(path) or ".",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            logger.warning("临时文件清理失败: %s", tmp_path, exc_info=True)
        raise


def batch_replace_label(
    json_dir: str,
    old_label: str,
    new_label: str,
) -> int:
    """批量替换标注 JSON 中的标签名。

    Args:
        json_dir: 标注文件目录。
        old_label: 旧标签名。
        new_label: 新标签名。

    Returns:
        修改的文件数。
    """
    count = 0
    for f in os.listdir(json_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(json_dir, f)
        try:
            doc = load_labelme(path)
        except (AppError, json.JSONDecodeError, OSError, KeyError, ValueError):
            # L1（2026-10-06 三轮审查）：load_labelme 对损坏 JSON 抛
            # AnnotationIOError（AppError 子类）——旧元组捕不到，坏文件
            # 会击穿"跳过"意图崩掉整个批量任务（实测复现）。AppError
            # 覆盖全部标注 IO 异常族。
            logger.debug("跳过损坏标注文件: %s", path)
            continue
        changed = False
        for s in doc.get("shapes", []):
            if s.get("label") == old_label:
                s["label"] = new_label
                changed = True
        if changed:
            atomic_write_json(path, doc)
            count += 1
    return count


def label_data_statistics(json_dir: str) -> dict[str, int]:
    """统计标注数据中各类别的数量分布。

    Args:
        json_dir: 标注文件目录。

    Returns:
        {label_name: count} 字典，按数量降序。
    """
    stats: dict[str, int] = {}
    for f in os.listdir(json_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(json_dir, f)
        try:
            doc = load_labelme(path)
        except (AppError, json.JSONDecodeError, OSError, KeyError, ValueError):
            logger.debug("跳过损坏标注文件: %s", path)  # L1：同 batch_replace_label
            continue
        for s in doc.get("shapes", []):
            label = s.get("label", "unknown")
            stats[label] = stats.get(label, 0) + 1
    # 按数量降序排序
    return dict(sorted(stats.items(), key=lambda x: -x[1]))


def batch_delete_labels(
    json_dir: str,
    labels_to_delete: list[str],
) -> int:
    """批量删除指定标签名的标注。

    Args:
        json_dir: 标注文件目录。
        labels_to_delete: 要删除的标签名列表。

    Returns:
        修改的文件数。
    """
    delete_set = set(labels_to_delete)
    count = 0
    for f in os.listdir(json_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(json_dir, f)
        try:
            doc = load_labelme(path)
        except (AppError, json.JSONDecodeError, OSError, KeyError, ValueError):
            logger.debug("跳过损坏标注文件: %s", path)  # L1：同 batch_replace_label
            continue
        original_len = len(doc.get("shapes", []))
        doc["shapes"] = [
            s for s in doc.get("shapes", [])
            if s.get("label") not in delete_set
        ]
        if len(doc["shapes"]) != original_len:
            atomic_write_json(path, doc)
            count += 1
    return count


__all__ = [
    "batch_replace_label",
    "label_data_statistics",
    "batch_delete_labels",
]
