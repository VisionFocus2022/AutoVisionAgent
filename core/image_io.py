"""统一图像读取（W1-T3，P2-5）——Windows 中文路径安全。

裸 ``cv2.imread`` 在 Windows 下对非系统码页路径返回 None（本项目根目录即
中文路径，对照实验见 tests/test_image_io.py::test_cv2_imread_fails_on_chinese_path_control）。
本模块用 ``np.fromfile + cv2.imdecode`` 绕开该限制；cv2 不可用时回退 PIL。

契约与 ``cv2.imread`` 对齐：返回 BGR ndarray；文件不存在或解码失败返回 None。
"""
from __future__ import annotations

import os
from typing import Any


def imread_unicode(path: str | Any, flags: int | None = None) -> Any | None:
    """中文路径安全读图。

    Args:
        path: 图像路径（str / Path）。
        flags: cv2 读取标志；默认 IMREAD_COLOR（与 cv2.imread 默认一致）。

    Returns:
        numpy.ndarray（BGR，cv2 路径）；cv2 缺失时为 PIL 读出的 RGB。
        两条路径都失败时返回 None（不抛异常，与 cv2.imread 契约一致）。
    """
    p = str(path)
    try:
        import cv2
        import numpy as np

        data = np.fromfile(p, dtype=np.uint8)
        if data.size:
            img = cv2.imdecode(data, flags if flags is not None else cv2.IMREAD_COLOR)
            if img is not None:
                return img
    except ImportError:
        pass  # cv2/numpy 不可用 → 走 PIL 回退
    except OSError:
        return None  # 文件不存在等 IO 错误

    try:
        import numpy as np
        from PIL import Image

        with Image.open(p) as im:
            # M9（2026-10-05 二轮审查·根因修复）：PIL 回退统一转 BGR——
            # 此前同函数两种通道语义（cv2 路径 BGR、PIL 路径 RGB），下游
            # 按任一语义消费都会在另一条路径上颜色错乱（vision_dataset
            # 的 cvtColor(BGR2RGB) 在 PIL 路径上会把 RGB 翻成 BGR 即其
            # 下游受害点）。契约收敛：本函数恒返回 BGR（模块 docstring
            # 已如此声明，此处使实现对齐声明）。
            rgb = np.asarray(im.convert("RGB"))
            return rgb[..., ::-1]  # RGB → BGR（零拷贝视图翻转）
    except Exception:  # noqa: BLE001 —— 与 cv2.imread 契约对齐：失败返回 None
        return None


def imwrite_unicode(path: str | Any, img: Any, ext: str = ".png") -> bool:
    """中文路径安全写图（与 cv2.imwrite 契约对齐：成功返回 bool）。

    Args:
        path: 目标路径（str / Path）。扩展名缺失时追加 ``ext``。
        img: numpy 数组（BGR 语义，与 cv2.imwrite 一致）。
        ext: path 无扩展名时使用的默认扩展名。

    Returns:
        是否写入成功。
    """
    p = str(path)
    if not os.path.splitext(p)[1]:
        p += ext
    try:
        import cv2
        import numpy as np

        ok, buf = cv2.imencode(os.path.splitext(p)[1] or ".png", np.asarray(img))
        if not ok:
            return False
        buf.tofile(p)
        return True
    except Exception:  # noqa: BLE001 —— 与 cv2.imwrite 契约对齐：失败返回 False
        return False


__all__ = ["imread_unicode", "imwrite_unicode"]
