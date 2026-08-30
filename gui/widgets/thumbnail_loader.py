"""异步缩略图加载器（R5-5；W9 QImage 线程安全化）。

在 QThreadPool 中解码图像并缩放到图标尺寸，通过信号回传到主线程。
线程内使用 QImage（Qt 契约：QPixmap 仅限主线程，QImage 可跨线程），
主线程回调处再转 QIcon——W9 修复 run() 在工作线程构造 QPixmap 的违例。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QImage, QPainter


class _Signals(QObject):
    """信号中转（QRunnable 不能直接继承 QObject + Signal）。"""

    loaded = Signal(str, QImage)  # (image_path, 缩放后 QImage)
    failed = Signal(str)          # image_path


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
        image = QImage(self.path)
        if image.isNull():
            self.signals.failed.emit(self.path)
            return
        image = image.scaled(
            self.size, self.size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        # W41：铺到恒定方形画布（保比例居中，不拉伸变形）——IconMode
        # 条目尺寸随 pixmap 实际宽高浮动导致网格错位（用户报障：
        # 行首左缘不齐、图片间距不均）
        if image.width() != self.size or image.height() != self.size:
            canvas = QImage(self.size, self.size, QImage.Format_ARGB32)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            painter.drawImage(
                (self.size - image.width()) // 2,
                (self.size - image.height()) // 2,
                image,
            )
            painter.end()
            image = canvas
        self.signals.loaded.emit(self.path, image)


__all__ = ["ThumbnailTask"]
