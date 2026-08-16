"""共享内存管理器（文件映射 MMF，跨进程零拷贝）。

设计动机
--------
gRPC 适合传递控制信令与小型结果元数据（检测框、置信度、标签），
但对大块二进制数据（4000x3000 原图、实例分割掩码 (N,H,W)、关键点数组）
逐次 protobuf 序列化开销显著。本模块在同一机器上用「文件映射内存」
（Windows: Memory-Mapped File；POSIX: mmap）承载这类大块数据，
gRPC 消息仅携带 ``SharedMemoryHandle``（路径/偏移/长度/dtype/shape），
由对端按句柄直接映射读取，达到零拷贝。

跨语言契约
----------
- 生产方（本服务写出结果时，或 C# 客户端送入大图时）创建临时文件，
  写入原始字节，返回 :class:`SharedMemoryHandle`。
- 消费方按 ``file_path`` 打开文件，``mmap`` 映射，按 ``offset/length/dtype/shape``
  解释为 numpy 数组。
- ``dtype`` 仅限：uint8 / float32 / float64 / bool。

实现说明
--------
- 采用「一区域一文件」简化模型：每个分配创建一个临时文件，
  避免多区域共享一文件带来的偏移对齐与并发回收复杂度。
- 文件由创建方拥有，``release`` 时删除；进程退出时未释放的文件由
  ``atexit`` 钩子兜底清理。
"""
from __future__ import annotations

import logging
import mmap
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# numpy dtype ↔ 字符串契约（与 .NET 侧 SharedMemoryReader 对齐）
_DTYPE_MAP: Dict[str, str] = {
    "uint8": "|u1",
    "float32": "<f4",
    "float64": "<f8",
    "bool": "|b1",
}
_NAME_TO_NP: Dict[str, str] = {v: k for k, v in _DTYPE_MAP.items()}


@dataclass(frozen=True)
class SharedMemoryHandle:
    """共享内存句柄（与 proto 同名结构体的 Python 镜像，便于内部传递）。

    encoding（W6-T2）：载荷编码，"raw"（原始字节，.NET 契约）或
    "bool_rle"（mask_codec 游程压缩，仅 Python 读端支持；proto 侧由
    dtype="bool_rle" 标记携带）。
    """

    file_path: str
    offset: int
    length: int
    dtype: str
    shape: Tuple[int, ...]
    encoding: str = "raw"

    def to_proto(self):
        """转换为 protobuf 消息。"""
        from serving.proto import autovisionagent_pb2 as pb

        return pb.SharedMemoryHandle(
            file_path=self.file_path,
            offset=int(self.offset),
            length=int(self.length),
            dtype=self.dtype,
            shape=list(self.shape),
        )

    @classmethod
    def from_proto(cls, msg) -> "SharedMemoryHandle":
        return cls(
            file_path=msg.file_path,
            offset=int(msg.offset),
            length=int(msg.length),
            dtype=msg.dtype,
            shape=tuple(msg.shape),
        )


class SharedMemoryManager:
    """共享内存区域生命周期管理器（线程安全）。

    用法::

        mgr = SharedMemoryManager()
        handle = mgr.write_array(arr)          # 写出 numpy 数组
        arr2 = mgr.read_array(handle)          # 读回（本进程或对端进程）
        mgr.release(handle.file_path)          # 显式回收

    注意：``read_array`` 对任意 ``SharedMemoryHandle`` 都可工作（不限于本管理器
    创建的），因此 Python 服务既能写出结果掩码，也能读入 C# 送来的大图。
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        # 默认放到系统临时目录下的 autovisionagent_shm 子目录，便于统一清理
        if base_dir is None:
            base_dir = os.path.join(
                os.environ.get("TEMP", os.environ.get("TMP", str(Path.home()))),
                "autovisionagent_shm",
            )
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        # file_path -> (fd, mmap_obj)：仅记录本进程创建的区域，用于回收
        self._regions: Dict[str, Tuple[int, mmap.mmap]] = {}

        import atexit
        atexit.register(self.cleanup)

    # ---------- 写出 ----------

    def write_array(self, array, dtype: Optional[str] = None) -> SharedMemoryHandle:
        """将 numpy 数组以连续字节写入新建的共享内存文件。

        Args:
            array: numpy 数组（会被强制转为 C 连续）。
            dtype: 覆盖 dtype 名称；默认按数组 dtype 推断。

        Returns:
            该区域的 :class:`SharedMemoryHandle`。
        """
        import numpy as np

        arr = np.ascontiguousarray(array)
        dt_name = dtype or _np_dtype_name(arr.dtype)

        if dt_name not in _DTYPE_MAP:
            raise ValueError(
                f"不支持的 dtype: {dt_name}，仅支持 {list(_DTYPE_MAP)}"
            )

        raw = arr.tobytes(order="C")
        return self._write_raw(raw, dt_name, tuple(int(s) for s in arr.shape))

    def write_bytes(self, data: bytes, dtype: str = "uint8", shape: Tuple[int, ...] = ()) -> SharedMemoryHandle:
        """写入裸字节并给定 dtype/shape（用于非 numpy 来源）。"""
        if dtype not in _DTYPE_MAP:
            raise ValueError(f"不支持的 dtype: {dtype}，仅支持 {list(_DTYPE_MAP)}")
        return self._write_raw(bytes(data), dtype, tuple(int(s) for s in shape))

    def write_mask_compact(self, masks) -> SharedMemoryHandle:
        """bool 掩码走 RLE 压缩写出（W6-T2，对标 CompactMask 游程编码）。

        dtype="bool_rle"（经 mask_codec 编码；read_array 自动解码）。
        ⚠️ 跨语言注意：.NET SharedMemoryReader 需支持 bool_rle 才能消费该句柄；
        gRPC Detect 默认仍走 raw（serialization 由 AVA_SHM_MASK_RLE 开关控制）。
        """
        import numpy as np

        arr = np.asarray(masks)
        if arr.dtype != np.bool_:
            arr = arr.astype(np.bool_)
        from serving.mask_codec import encode_mask_rle

        payload = encode_mask_rle(arr)
        return self._write_raw(payload, "bool_rle", tuple(int(s) for s in arr.shape))

    def _write_raw(self, raw: bytes, dtype: str, shape: Tuple[int, ...]) -> SharedMemoryHandle:
        name = f"ava_{uuid.uuid4().hex}.bin"
        path = str(self._base_dir / name)

        # 创建文件并预占空间（Windows 必须显式 O_BINARY：缺省文本模式会把
        # 二进制流中的 0x0A 翻译成 0x0D 0x0A，静默破坏数组数据——W3-T4 测试实测）
        flags = os.O_RDWR | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, raw)
            os.fsync(fd)
            length = len(raw)
            mm = mmap.mmap(fd, length, access=mmap.ACCESS_READ)
        except Exception:
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

        with self._lock:
            self._regions[path] = (fd, mm)
        logger.debug("共享内存写出: %s (%d bytes, %s, shape=%s)", path, length, dtype, shape)
        return SharedMemoryHandle(
            file_path=path, offset=0, length=length, dtype=dtype, shape=shape
        )

    # ---------- 读入 ----------

    def read_array(self, handle) -> "numpy.ndarray":
        """按句柄读取并重建为 numpy 数组。

        适用于任意句柄（本进程或对端进程创建）。dtype=="bool_rle" 时
        经 mask_codec 解码还原 bool 掩码（W6-T2）。
        """
        import numpy as np

        h = _coerce_handle(handle)

        if h.dtype == "bool_rle":
            from serving.mask_codec import decode_mask_rle

            data = self.read_bytes(h)
            return decode_mask_rle(data, h.shape)

        if h.dtype not in _DTYPE_MAP:
            raise ValueError(f"不支持的 dtype: {h.dtype}，仅支持 {list(_DTYPE_MAP)}")

        np_dtype = np.dtype(_DTYPE_MAP[h.dtype])

        # 优先复用本进程已映射的区域，否则按路径打开对端创建的文件
        with self._lock:
            entry = self._regions.get(h.file_path)

        if entry is not None:
            _fd, mm = entry
            data = mm[h.offset : h.offset + h.length]
        else:
            data = _read_range_from_file(h.file_path, h.offset, h.length)

        arr = np.frombuffer(data, dtype=np_dtype)
        if h.shape:
            arr = arr.reshape(h.shape)
        return arr

    def read_bytes(self, handle) -> bytes:
        """按句柄读取为裸字节。"""
        h = _coerce_handle(handle)
        with self._lock:
            entry = self._regions.get(h.file_path)
        if entry is not None:
            _fd, mm = entry
            return bytes(mm[h.offset : h.offset + h.length])
        return _read_range_from_file(h.file_path, h.offset, h.length)

    # ---------- 回收 ----------

    def release(self, file_path: str) -> bool:
        """释放指定区域（关闭映射并删除文件）。

        Returns:
            是否命中并回收了本进程创建的区域。对端创建的文件由其自行回收。
        """
        with self._lock:
            entry = self._regions.pop(file_path, None)

        if entry is None:
            # 非本进程创建：仅尝试删除文件（通常不应由本侧负责）
            logger.debug("release 未命中本进程区域: %s", file_path)
            return False

        fd, mm = entry
        try:
            mm.close()
        except (BufferError, OSError):
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(file_path)
        except OSError:
            pass
        logger.debug("共享内存已回收: %s", file_path)
        return True

    def cleanup(self) -> None:
        """进程退出时兜底清理所有未释放区域。"""
        with self._lock:
            paths = list(self._regions.keys())
        for p in paths:
            try:
                self.release(p)
            except Exception:
                logger.warning("清理共享内存 %s 失败", p, exc_info=True)


# ------------------------------ 模块级辅助 ------------------------------ #

def _np_dtype_name(np_dtype) -> str:
    """numpy.dtype -> 契约字符串。"""
    import numpy as np

    # 精确匹配常见类型
    for name, dt_str in _DTYPE_MAP.items():
        if np.dtype(np.dtype(dt_str)) == np.dtype(np_dtype):
            return name
    # 回退到 kind 粗判
    raise ValueError(f"无法映射 numpy dtype: {np_dtype}")


def _coerce_handle(handle) -> SharedMemoryHandle:
    """接受 SharedMemoryHandle / proto 消息，统一为 SharedMemoryHandle。"""
    if isinstance(handle, SharedMemoryHandle):
        return handle
    # proto 消息
    if hasattr(handle, "file_path") and hasattr(handle, "offset"):
        return SharedMemoryHandle.from_proto(handle)
    raise TypeError(f"无法识别的句柄类型: {type(handle)!r}")


def _read_range_from_file(file_path: str, offset: int, length: int) -> bytes:
    """从未映射的对端文件中读取指定区间。"""
    with open(file_path, "rb") as f:
        if offset:
            f.seek(offset)
        return f.read(length)


__all__ = ["SharedMemoryHandle", "SharedMemoryManager"]
