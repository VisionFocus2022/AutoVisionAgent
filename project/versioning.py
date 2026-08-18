"""数据集版本管理核心库（W19 v3 第三波 FR-4.1 / AC-4.1~4.2，纯函数零 Qt 依赖）。

对标 v3 架构报告 #17：以"快照 + manifest 哈希清单"提供项目数据集的
版本管理，弥补此前标注/图像误删误改无回滚手段的领域缺口。

核心语义（PRD docs/prd-wave19-v3-wave3.md FR-4）：
- build_manifest(root)：遍历项目树（跳过 ``.snapshots/`` 自身），
  ``{相对路径 posix: {sha256, size}}``（64KiB 分块哈希）。
- create_snapshot(project_root, label)：``.snapshots/{YYYYmmdd-HHMMSS}_{label}/``
  镜像项目树，每文件优先 NTFS 硬链（O(1) 不复制数据块；OSError 回退
  shutil.copy2，跨卷/权限场景），manifest.json 原子写（temp + os.replace）。
- diff_manifests(old, new)：``{"added": [...], "removed": [...], "changed": [...]}``
  （changed = 同路径 sha256 不同）。
- verify_snapshot(snapshot_dir)：重哈希对照 manifest，报告问题列表
  （文件缺失 / 哈希不符——硬链共享块被就地改写的检测手段）。
- restore_snapshot(project_root, snapshot_dir)：**非破坏性**——先 verify
  （corrupted 则 raise），仅回拷改动/缺失文件（copy2 而非再硬链，断开
  inode 共享），快照后新增文件一律保留；返回 ``{"restored": n, "kept_new": m}``。
- list_snapshots(project_root)：按时间排序 ``[(dir, label, 条目数)]``。

硬链一致性约定：快照不可变的前提是项目文件按"原子替换"（temp +
os.replace，规范编辑器行为）修改；若就地改写（r+b 写穿同一 inode），
共享块被污染，verify_snapshot 会如实报告 corrupted 并阻止 restore。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# 快照根目录名（build_manifest 遍历时跳过，快照不进清单）
SNAPSHOT_DIRNAME = ".snapshots"
MANIFEST_NAME = "manifest.json"
# W19 FR-4.1：64KiB 分块哈希——大图不整读进内存
_HASH_CHUNK = 64 * 1024
# 快照目录名：{YYYYmmdd-HHMMSS}_{label}（排序即时间序）
_SNAPSHOT_NAME_RE = re.compile(r"^(\d{8}-\d{6})_(.+)$")
# Windows 保留文件名字符 + 空白 → 下划线
_UNSAFE_LABEL_RE = re.compile(r'[<>:"/\\|?*\s]+')


def _sha256_file(path: str) -> str:
    """分块计算文件 SHA-256（64KiB/块，不整读大文件进内存）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(_HASH_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _rel_posix(root: str, path: str) -> str:
    """相对路径转 posix 分隔（manifest 键跨平台一致）。"""
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def _manifest_path(snapshot_dir: str) -> str:
    return os.path.join(snapshot_dir, MANIFEST_NAME)


def build_manifest(root: str) -> Dict[str, Dict[str, object]]:
    """遍历项目树构建哈希清单。

    Args:
        root: 项目根目录。

    Returns:
        ``{相对路径 posix: {"sha256": hex, "size": bytes}}``；
        ``.snapshots`` 目录被跳过（快照自身不入清单）。
    """
    manifest: Dict[str, Dict[str, object]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # W19 FR-4.1：跳过 .snapshots（任意深度），快照不进清单
        dirnames[:] = [d for d in dirnames if d != SNAPSHOT_DIRNAME]
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
                manifest[_rel_posix(root, full)] = {
                    "sha256": _sha256_file(full),
                    "size": st.st_size,
                }
            except OSError as exc:
                # 单文件读取失败不中断整树清单（并发删除等瞬时态），如实落日志
                logger.warning("build_manifest 跳过不可读文件 %s: %s", full, exc)
    return manifest


def load_manifest(snapshot_dir: str) -> Dict[str, Dict[str, object]]:
    """读取快照 manifest.json 的 files 清单。

    Args:
        snapshot_dir: 快照目录。

    Returns:
        ``{相对路径 posix: {"sha256": ..., "size": ...}}``。

    Raises:
        ValueError: manifest.json 缺失或 JSON 损坏（诚实失败，不猜内容）。
    """
    path = _manifest_path(snapshot_dir)
    if not os.path.isfile(path):
        raise ValueError(f"快照缺少 {MANIFEST_NAME}: {snapshot_dir}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        files = payload["files"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"快照 {MANIFEST_NAME} 损坏: {path} ({exc})") from exc
    return files


def _safe_label(label: str) -> str:
    """净化标签为合法目录名片段（Windows 保留字符 → 下划线，去首尾点/下划线）。"""
    cleaned = _UNSAFE_LABEL_RE.sub("_", label).strip("._")
    return cleaned or "snapshot"


def _link_or_copy(src: str, dst: str) -> None:
    """优先硬链（O(1)），OSError（跨卷/权限/不支持）回退 copy2。"""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def create_snapshot(project_root: str, label: str) -> str:
    """创建项目快照：镜像项目树（硬链）+ 原子写 manifest.json。

    Args:
        project_root: 项目根目录。
        label: 快照标签（非法文件名字符自动净化）。

    Returns:
        快照目录路径 ``{project_root}/.snapshots/{时间戳}_{label}/``。
        同秒同名冲突时追加 ``-2``、``-3``… 序号。
    """
    snap_root = os.path.join(project_root, SNAPSHOT_DIRNAME)
    os.makedirs(snap_root, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{timestamp}_{_safe_label(label)}"
    snap_dir = os.path.join(snap_root, base)
    suffix = 1
    while os.path.exists(snap_dir):  # 同秒同名碰撞 → 序号后缀
        suffix += 1
        snap_dir = os.path.join(snap_root, f"{base}-{suffix}")
    os.makedirs(snap_dir)

    manifest = build_manifest(project_root)
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d != SNAPSHOT_DIRNAME]
        rel_dir = _rel_posix(project_root, dirpath)
        mirror_dir = (
            snap_dir if rel_dir == "." else os.path.join(snap_dir, *rel_dir.split("/"))
        )
        os.makedirs(mirror_dir, exist_ok=True)
        for name in filenames:
            _link_or_copy(
                os.path.join(dirpath, name), os.path.join(mirror_dir, name)
            )

    # W19 FR-4.1：manifest 原子写——temp + os.replace，中途崩溃不留半份清单
    payload = {
        "label": label,
        "created_at": timestamp,
        "files": manifest,
    }
    tmp = os.path.join(snap_dir, MANIFEST_NAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, _manifest_path(snap_dir))

    logger.info(
        "已创建快照 %s/%s（%d 个文件）", SNAPSHOT_DIRNAME,
        os.path.basename(snap_dir), len(manifest),
    )
    return snap_dir


def diff_manifests(
    old: Dict[str, Dict[str, object]], new: Dict[str, Dict[str, object]]
) -> Dict[str, List[str]]:
    """对比两份清单，按三类归并（纯函数，不触碰文件系统）。

    Args:
        old: 旧清单（如较早快照）。
        new: 新清单（如当前项目或较新快照）。

    Returns:
        ``{"added": 新增路径, "removed": 删除路径, "changed": 同路径哈希变更}``，
        各列表按路径排序。
    """
    added = sorted(p for p in new if p not in old)
    removed = sorted(p for p in old if p not in new)
    changed = sorted(
        p
        for p in old
        if p in new and old[p]["sha256"] != new[p]["sha256"]  # type: ignore[union-attr]
    )
    return {"added": added, "removed": removed, "changed": changed}


def verify_snapshot(snapshot_dir: str) -> List[str]:
    """校验快照完整性：重哈希对照 manifest，返回问题列表。

    检测两类问题（含硬链共享块被源文件就地改写的场景）：
    - 文件缺失：清单条目在快照目录中不存在；
    - 哈希不符：文件内容与清单记录的 sha256 不一致。

    Args:
        snapshot_dir: 快照目录。

    Returns:
        问题描述列表（空列表 = 完好）。

    Raises:
        ValueError: manifest.json 缺失或损坏（非法快照）。
    """
    manifest = load_manifest(snapshot_dir)
    problems: List[str] = []
    for rel, entry in sorted(manifest.items()):
        path = os.path.join(snapshot_dir, *rel.split("/"))
        if not os.path.isfile(path):
            problems.append(f"{rel}: 文件缺失")
            continue
        if _sha256_file(path) != entry["sha256"]:
            problems.append(f"{rel}: 哈希不符（就地改写或块损坏）")
    return problems


def restore_snapshot(project_root: str, snapshot_dir: str) -> Dict[str, int]:
    """非破坏性恢复：把项目树回滚到快照状态，保留快照后新增文件。

    语义（docstring 即契约，PRD FR-4.1）：
    1. 先 verify_snapshot——快照损坏（共享块被写穿/文件缺失）则 raise
       ValueError（含问题清单），绝不把污染拷回项目；
    2. manifest 每条：项目文件缺失或哈希与快照不符 → 从快照 shutil.copy2
       回拷（copy 而非再硬链——恢复出的项目文件与快照断开 inode 共享，
       之后就地改写项目文件不再污染快照）；
    3. 快照后新增文件（不在 manifest 中）一律保留，不删除。

    Args:
        project_root: 项目根目录。
        snapshot_dir: 快照目录。

    Returns:
        ``{"restored": 回拷文件数, "kept_new": 保留的新增文件数}``。

    Raises:
        ValueError: 快照损坏或非法（问题清单随异常信息给出）。
    """
    problems = verify_snapshot(snapshot_dir)
    if problems:
        raise ValueError(
            f"快照已损坏，拒绝恢复（{len(problems)} 处问题）: "
            + "; ".join(problems)
        )

    manifest = load_manifest(snapshot_dir)
    current = build_manifest(project_root)
    restored = 0
    for rel, entry in sorted(manifest.items()):
        cur = current.get(rel)
        if cur is not None and cur["sha256"] == entry["sha256"]:
            continue  # 项目现状与快照一致，无需回拷
        src = os.path.join(snapshot_dir, *rel.split("/"))
        dst = os.path.join(project_root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst) or project_root, exist_ok=True)
        shutil.copy2(src, dst)  # copy 而非硬链：断开与快照的 inode 共享
        restored += 1
    kept_new = sum(1 for p in current if p not in manifest)
    logger.info(
        "已从快照恢复 %s：回拷 %d 个文件，保留 %d 个新增文件",
        os.path.basename(snapshot_dir), restored, kept_new,
    )
    return {"restored": restored, "kept_new": kept_new}


def list_snapshots(project_root: str) -> List[Tuple[str, str, int]]:
    """列出项目全部合法快照，按时间（目录名时间戳）升序。

    Args:
        project_root: 项目根目录。

    Returns:
        ``[(快照目录绝对路径, 标签, manifest 条目数)]``；
        仅收录命名合规（``{时间戳}_{label}``）且 manifest.json 可读的目录。
    """
    snap_root = os.path.join(project_root, SNAPSHOT_DIRNAME)
    if not os.path.isdir(snap_root):
        return []
    out: List[Tuple[str, str, int]] = []
    for name in os.listdir(snap_root):
        full = os.path.join(snap_root, name)
        match = _SNAPSHOT_NAME_RE.match(name)
        if not match or not os.path.isdir(full):
            continue
        try:
            count = len(load_manifest(full))
        except ValueError:
            continue  # manifest 缺失/损坏的目录不是合法快照，不参与列举
        out.append((full, match.group(2), count))
    # 时间戳前缀保证字典序 = 时间序；同秒内按 label 序
    out.sort(key=lambda item: os.path.basename(item[0]))
    return out


__all__ = [
    "SNAPSHOT_DIRNAME",
    "build_manifest",
    "load_manifest",
    "create_snapshot",
    "diff_manifests",
    "verify_snapshot",
    "restore_snapshot",
    "list_snapshots",
]
