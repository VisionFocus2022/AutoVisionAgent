"""文件对话框公共辅助（R4-13）。

统一封装 QFileDialog 调用，消除 19+ 处重复代码，
支持最近目录记忆和翻译键管理。
"""
from __future__ import annotations

import json
import os

from PySide6.QtWidgets import QFileDialog, QWidget

from gui.core.i18n import tr

# 最近目录记忆文件
_LAST_DIR_FILE = os.path.join(os.path.expanduser("~"), ".autovision_last_dir.json")


def _load_last_dir(key: str = "last_dir") -> str:
    """加载最近使用的目录。"""
    try:
        if os.path.exists(_LAST_DIR_FILE):
            with open(_LAST_DIR_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return data.get(key, "")
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def _save_last_dir(path: str, key: str = "last_dir") -> None:
    """保存最近使用的目录。"""
    if not path:
        return
    directory = os.path.dirname(path) if os.path.isfile(path) else path
    try:
        data = {}
        if os.path.exists(_LAST_DIR_FILE):
            with open(_LAST_DIR_FILE, encoding="utf-8") as f:
                data = json.load(f)
        data[key] = directory
        with open(_LAST_DIR_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except (OSError, json.JSONDecodeError, TypeError):
        pass


def pick_open_file(
    parent: QWidget,
    title_key: str,
    flt: str = "",
    remember_key: str = "last_open",
) -> str:
    """打开文件选择对话框，返回选中路径（空字符串表示取消）。

    Args:
        parent: 父窗口。
        title_key: 标题翻译键（将传入 tr()）。
        flt: 文件过滤器（如 "Images (*.png *.jpg)"）。
        remember_key: 最近目录记忆键。
    """
    start_dir = _load_last_dir(remember_key)
    path, _ = QFileDialog.getOpenFileName(parent, tr(title_key), start_dir, flt)
    if path:
        _save_last_dir(path, remember_key)
    return path


def pick_save_file(
    parent: QWidget,
    title_key: str,
    flt: str = "",
    remember_key: str = "last_save",
) -> str:
    """保存文件选择对话框，返回选中路径。"""
    start_dir = _load_last_dir(remember_key)
    path, _ = QFileDialog.getSaveFileName(parent, tr(title_key), start_dir, flt)
    if path:
        _save_last_dir(path, remember_key)
    return path


def pick_directory(
    parent: QWidget,
    title_key: str,
    remember_key: str = "last_dir",
) -> str:
    """目录选择对话框，返回选中路径。"""
    start_dir = _load_last_dir(remember_key)
    path = QFileDialog.getExistingDirectory(parent, tr(title_key), start_dir)
    if path:
        _save_last_dir(path, remember_key)
    return path


__all__ = ["pick_open_file", "pick_save_file", "pick_directory"]
