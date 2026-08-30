"""通用路径 I/O 助手：把含非 ASCII 字符的路径喂给窄字符 C 库时用的临时拷贝。

背景：许多原生扩展（最典型的是 ``cv2.dnn_superres.DnnSuperResImpl.readModel``，底层走
``cv::dnn::ReadProtoFromBinaryFile``）在 Windows 上用窄字符（``char *``）文件 API 打开权重文件。
当路径含非 ASCII 字符（本项目根路径即含中文）时，窄字符 API 无法表达该路径 →
静默读失败 → 引擎加载崩在 ``readModel``，外层只能看到模糊的 "ReadProtoFromBinaryFile failed"。

修法：先尝试 ``path.encode("ascii")``——纯 ASCII 路径走快路径，零拷贝；``UnicodeEncodeError``
则用 OS 的 Unicode 文件 API（``open(src, 'rb')`` / ``open(tmp, 'wb')``，文件名原样透传，安全）
把字节拷一份到 ``tempfile.mkstemp`` 给的纯 ASCII 名临时文件，把临时路径喂给窄字符 C 库，
``finally`` 删除临时文件。

与 ``core/image_io.py`` 的 ``imread_unicode`` 平级、同思路（绕开窄字符 API）、不同职责：
- ``image_io``：图像 I/O（``np.fromfile`` + ``cv2.imdecode`` 解码图像字节）
- ``path_io``：通用路径 I/O（拷一份 ASCII 名临时文件给任意窄字符 C 库用）

典型用法::

    from core.path_io import ascii_path_copy

    with ascii_path_copy(weights_path) as (ascii_path, was_copied):
        sr.readModel(ascii_path)  # cv2.dnn 窄字符 C 库，中文路径下不再崩

``was_copied`` 为 ``True`` 表示做了临时拷贝（调用方可用于日志/诊断），``False`` 表示快路径直通。
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager

__all__ = ["ascii_path_copy"]


@contextmanager
def ascii_path_copy(path: str | os.PathLike[str]) -> Generator[tuple[str, bool], None, None]:
    """把任意路径临时转成纯 ASCII 路径，便于喂给窄字符 C 库。

    快路径：``path`` 可 ASCII 编码 → 直接 yield ``(str(path), False)``，不拷贝、不分配。
    慢路径：``path`` 含非 ASCII → 字节级拷贝到 ``tempfile.mkstemp`` 的 ASCII 名临时文件，
    yield ``(tmp_path, True)``，``finally`` 中 ``os.unlink`` 临时文件。

    Raises:
        OSError: 慢路径下源文件读失败或临时文件写失败（I/O 错误如实抛，不吞）。
    """
    src = os.fspath(path)
    try:
        src.encode("ascii")
    except UnicodeEncodeError:
        pass
    else:
        # 快路径：纯 ASCII，零拷贝直通
        yield (src, False)
        return

    # 慢路径：含非 ASCII，拷一份到 ASCII 名临时文件
    fd, tmp_path = tempfile.mkstemp(suffix="_dnn.pb")
    # 立即关闭底层 fd，下面用 open() 重新打开以走 OS Unicode 文件 API 读写
    os.close(fd)
    try:
        with open(src, "rb") as fsrc, open(tmp_path, "wb") as fdst:
            # 分块拷贝，避免一次性把大权重文件全读进内存
            while True:
                chunk = fsrc.read(1 << 20)  # 1 MiB
                if not chunk:
                    break
                fdst.write(chunk)
        yield (tmp_path, True)
    finally:
        # 临时文件删除失败不掩盖业务异常：忽略
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
