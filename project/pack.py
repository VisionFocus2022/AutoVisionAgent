"""项目包 2.0：资产迁移（W3-2，roadmap Wave3）。

export_pack：项目根目录 → zip（相对路径 + avpack_manifest.json 逐文件
SHA256）。import_pack：三段式安全导入——读 manifest → **先验校验**
（zip 内容哈希全对照，失配列名）→ 校验全过才落盘；目标已存在=拒绝
覆盖（导入是数据变更类操作，本模块的破坏面=零：要么完整落盘、要么
零落盘带显式错误）。

纯后端（无 Qt），中文路径直写。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import zipfile

logger = logging.getLogger(__name__)

PACK_FORMAT = "avpack/1"
MANIFEST_NAME = "avpack_manifest.json"
_SKIP_DIRS = {"__pycache__", ".thumbnails"}
_SKIP_NAMES = {".DS_Store", "Thumbs.db"}


class PackError(Exception):
    """项目包错误（缺件/损坏/碰撞——消息面向用户可直接展示）。"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iter_project_files(project_root: str):
    """项目根 → 相对路径迭代（跳缓存/缩略图/系统杂项）。"""
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in sorted(filenames):
            if name in _SKIP_NAMES or name == MANIFEST_NAME:
                continue
            full = os.path.join(dirpath, name)
            yield os.path.relpath(full, project_root).replace("\\", "/"), full


def export_pack(project_root: str, zip_path: str) -> dict:
    """项目根 → 项目包 zip（W3-2 FR-1）。Returns: manifest dict。"""
    if not os.path.isdir(project_root):
        raise PackError(f"项目目录不存在: {project_root}")
    files: dict[str, str] = {}  # relpath -> sha256
    total_bytes = 0
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, full in _iter_project_files(project_root):
            with open(full, "rb") as fh:
                data = fh.read()
            zf.writestr(rel, data)
            files[rel] = _sha256_bytes(data)
            total_bytes += len(data)
        try:
            from importlib.metadata import version as _pkg_version

            app_version = _pkg_version("autovisionagent")
        except Exception:  # noqa: BLE001  # 未安装态（源码跑）回退未知
            app_version = "unknown"
        manifest = {
            "format": PACK_FORMAT,
            "app_version": app_version,
            "project_dirname": os.path.basename(
                os.path.normpath(project_root)
            ),
            "files": files,
            "file_count": len(files),
            "total_bytes": total_bytes,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        zf.writestr(MANIFEST_NAME, json.dumps(
            manifest, ensure_ascii=False, indent=1))
    logger.info("项目包已导出: %s（%d 文件 %.1f KB）→ %s",
                manifest["project_dirname"], len(files),
                total_bytes / 1024, zip_path)
    return manifest


def import_pack(zip_path: str, base_root: str) -> dict:
    """项目包 → 导入 base_root/<项目目录名>（W3-2 FR-1 三段式）。

    Returns: {"project_dir": str, "file_count": int}；
    任何失配/缺件/碰撞 → PackError（零落盘）。
    """
    if not os.path.isfile(zip_path):
        raise PackError(f"项目包不存在: {zip_path}")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise PackError(f"不是有效的 zip 项目包: {exc}") from exc
    with zf:
        # ① manifest
        names = set(zf.namelist())
        if MANIFEST_NAME not in names:
            raise PackError("缺少清单文件 avpack_manifest.json（非本项目包格式）")
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PackError(f"清单文件损坏: {exc}") from exc
        files = manifest.get("files") or {}
        dirname = str(manifest.get("project_dirname") or "").strip()
        if not dirname or "/" in dirname or "\\" in dirname or ".." in dirname:
            raise PackError(f"清单内项目目录名非法: {dirname!r}")
        # ② 先验校验（缺件+哈希）
        missing = [r for r in files if r not in names]
        if missing:
            raise PackError(f"包内缺 {len(missing)} 个文件（清单有而 zip 无）: "
                            + ", ".join(missing[:3]))
        bad: list[str] = []
        for rel, expect in files.items():
            if _sha256_bytes(zf.read(rel)) != expect:
                bad.append(rel)
                if len(bad) >= 3:
                    break
        if bad:
            raise PackError(f"校验失败（内容与清单不符）: {', '.join(bad)}")
        # ③ 碰撞检查 + 落盘（先建临时名再原子改名？——zipfile 已全读，
        # 直接写目标即可；碰撞在写任何字节前判）
        target = os.path.join(base_root, dirname)
        if os.path.exists(target):
            raise PackError(f"目标已存在，拒绝覆盖: {dirname}（如需重导请先删除原项目）")
        os.makedirs(target, exist_ok=True)
        for rel in files:
            out = os.path.join(target, *rel.split("/"))
            os.makedirs(os.path.dirname(out) or target, exist_ok=True)
            with open(out, "wb") as fh:
                fh.write(zf.read(rel))
    logger.info("项目包已导入: %s（%d 文件）→ %s",
                dirname, len(files), base_root)
    return {"project_dir": target, "file_count": len(files)}


__all__ = ["PACK_FORMAT", "MANIFEST_NAME", "PackError", "export_pack",
           "import_pack"]
