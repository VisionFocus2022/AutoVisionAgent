"""异步缩略图加载器（R5-5）。

在 QThreadPool 中解码 QPixmap 并缩放到图标尺寸，
通过信号回传到主线程设置 QListWidgetItem 图标，
避免同步加载数百张图像时冻结 UI。
"""
from __future__ import annotations

from PySide6.QtCore import QRunnable, Qt, Signal, QObject
from PySide6.QtGui import QPixmap, QIcon


class _Signals(QObject):
    """信号中转（QRunnable 不能直接继承 QObject + Signal）。"""
    loaded = Signal(str, QIcon)   # (image_path, icon)
    failed = Signal(str)           # image_path


class ThumbnailTask(QRunnable):
    """单个缩略图加载任务。

    Parameters
    ----------
    path : str
        图像文件路径。
    size : int
        缩略图边长（像素），默认 120。
    """

    def __init__(self, path: str, size: int = 120) -> None:
        super().__init__()
        self.path = path
        self.size = size
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self) -> None:
        pm = QPixmap(self.path)
        if pm.isNull():
            self.signals.failed.emit(self.path)
            return
        pm = pm.scaled(
            self.size, self.size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.signals.loaded.emit(self.path, QIcon(pm))


__all__ = ["ThumbnailTask"]
