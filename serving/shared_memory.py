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
- 进程崩溃/强杀残留的 ava_*.bin 由下次启动清扫（mtime 年龄超 2 小时，
  W11 v2 P1-1）；区域登记数量有上限（默认 64，``AVA_SHM_MAX_REGIONS``
  或构造参数可调），写满即 RuntimeError，防静默泄漏。
- 区域 TTL（W17，v3 P1-1）：结果区域由客户端在 RPC 返回后即读，正常
  消费窗口远小于 TTL；超期未 release 的区域在下次写入前被惰性回收
  （不设后台线程），避免随附 C# 客户端无法回收结果区域时累积触顶上限。
  ``AVA_SHM_REGION_TTL_SECONDS`` 或构造参数可调，默认 300 秒，<=0 关闭。
- 区域租约（W19，v3 第三波 FR-2 方向 A，PoC）：``acquire_lease`` 在
  区域上登记一个有限时长的租约；租约未到期期间 ``_reap_expired``
  跳过该区域（与区域 TTL 是两个独立时钟，取长者保护）；
  ``release_leased`` 校验 lease_id 归属后才释放。生产路径
  （serialization 默认不建租约）行为不变——见 ADR-0002。
"""
from __future__ import annotations

import contextlib
import logging
import mmap
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # numpy 仅注解层使用，运行时按需函数内导入（保持启动轻量）
    import numpy

logger = logging.getLogger(__name__)

# numpy dtype ↔ 字符串契约（与 .NET 侧 SharedMemoryReader 对齐）
_DTYPE_MAP: dict[str, str] = {
    "uint8": "|u1",
    "float32": "<f4",
    "float64": "<f8",
    "bool": "|b1",
}
_NAME_TO_NP: dict[str, str] = {v: k for k, v in _DTYPE_MAP.items()}

# ---- 生命周期守护常量（W11 v2 P1-1）----
# 启动清扫的陈旧判定阈值：ava_*.bin 的 mtime 年龄超过该值即视为上次进程
# 崩溃/强杀的残留（区域是请求级短生命周期对象，正常路径由 release/atexit
# 回收，存活超过 2 小时的必然是泄漏）。
_STALE_FILE_MAX_AGE_SECONDS = 2 * 60 * 60
# 区域登记上限（防忘 release 的静默泄漏）；可经构造参数或环境变量注入。
_MAX_REGIONS_ENV = "AVA_SHM_MAX_REGIONS"
_DEFAULT_MAX_REGIONS = 64
# 区域 TTL（W17 v3 P1-1）：登记时长超过该秒数的区域在下次写入前被惰性回收。
_REGION_TTL_ENV = "AVA_SHM_REGION_TTL_SECONDS"
_DEFAULT_REGION_TTL_SECONDS = 300.0

# S1（安全审查 2026-10-05）：对端文件读取白名单。
# 默认开启：read_* 系列按文件路径读「对端创建的文件」时，仅允许位于
# base_dir 下且文件名匹配 ava_*.bin 的区域文件，杜绝把本模块当作任意
# 文件读取原语（FetchRegion 链路回环无鉴权，见 ADR-0001）。本进程在册
# 区域不受影响（其路径必为自建 ava_*.bin）。AVA_SHM_ALLOW_ANY_FILE=1
# 可显式放宽（测试/特殊部署需要，默认拒绝）。
_AVA_SHM_ALLOW_ANY_FILE_ENV = "AVA_SHM_ALLOW_ANY_FILE"


def _shm_path_allowed(file_path: str, base_dir: Path) -> bool:
    """S1：校验对端文件路径是否位于白名单内（base_dir 下 + ava_*.bin）。

    - 路径 resolve 后必须位于 base_dir 内（拒绝对端送来的绝对路径指向
      系统任意文件，如 users.json / license.key）；
    - 文件名必须匹配 ``ava_*.bin``（与双端命名契约一致，见
      dotnet_client AutoVisionAgentClient 的 ava_{Guid:N}.bin）；
    - 环境变量 AVA_SHM_ALLOW_ANY_FILE=1 可显式放宽（测试/特殊部署需要，
      默认拒绝）。
    """
    if os.environ.get(_AVA_SHM_ALLOW_ANY_FILE_ENV, "") == "1":
        return True
    p = Path(file_path)
    if p.name.startswith("ava_") and p.suffix == ".bin":
        try:
            p.resolve().relative_to(base_dir.resolve())
            return True
        except (ValueError, OSError):
            return False
    return False


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
    shape: tuple[int, ...]
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
    def from_proto(cls, msg) -> SharedMemoryHandle:
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

    def __init__(
        self,
        base_dir: str | None = None,
        max_regions: int | None = None,
        region_ttl_seconds: float | None = None,
    ) -> None:
        # 默认放到系统临时目录下的 autovisionagent_shm 子目录，便于统一清理
        if base_dir is None:
            base_dir = os.path.join(
                os.environ.get("TEMP", os.environ.get("TMP", str(Path.home()))),
                "autovisionagent_shm",
            )
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._max_regions = _resolve_max_regions(max_regions)
        self._region_ttl_seconds = _resolve_region_ttl(region_ttl_seconds)
        self._sweep_stale_files()

        self._lock = threading.Lock()
        # file_path -> (fd, mmap_obj, created_at_monotonic)：
        # 仅记录本进程创建的区域，用于回收与 TTL 计龄（W17 起三元组）
        self._regions: dict[str, tuple[int, mmap.mmap, float]] = {}
        # W19（v3 第三波 FR-2 方向 A）：区域租约登记表
        # file_path -> (lease_id, expires_at_monotonic)；lease_id 进程内自增。
        self._leases: dict[str, tuple[int, float]] = {}
        self._next_lease_id = 0

        import atexit
        atexit.register(self.cleanup)

    # ---------- 启动清扫 ----------

    def _sweep_stale_files(self) -> int:
        """删除本目录下陈旧的 ava_*.bin 残留（进程崩溃/强杀的兜底清扫）。

        仅按「ava_ 前缀 + .bin 后缀 + mtime 年龄超阈值」判定，其他文件一律
        不动（C# 客户端侧的文件清扫不在本模块职责内，属各自进程自理）。

        Returns:
            删除的文件数。
        """
        now = time.time()
        removed = 0
        for entry in self._base_dir.glob("ava_*.bin"):
            try:
                age = now - entry.stat().st_mtime
            except OSError:
                continue
            if age < _STALE_FILE_MAX_AGE_SECONDS:
                continue
            try:
                entry.unlink()
                removed += 1
            except OSError:
                # Windows 下被他进程占用的文件无法删除，留给下次启动再扫
                logger.warning("启动清扫陈旧共享内存文件失败: %s", entry, exc_info=True)
        if removed:
            logger.info(
                "启动清扫: 删除 %d 个陈旧共享内存文件 (目录=%s)", removed, self._base_dir
            )
        return removed

    # ---------- TTL 惰性回收（W17 v3 P1-1）----------

    def _reap_expired(self) -> int:
        """回收登记时长超过 TTL 的区域（写路径入口调用，不设后台线程）。

        结果区域由客户端在 RPC 返回后即读，正常消费窗口远小于 TTL；超期
        未 release 的视为泄漏（随附 C# 客户端结构性无法回收结果区域），
        回收以避免累积触顶 ``AVA_SHM_MAX_REGIONS``。TTL<=0 时直接跳过。
        锁不可重入：快照在锁内取、release 在锁外做（与 cleanup 同模式）。

        Returns:
            本次回收的区域数。
        """
        ttl = self._region_ttl_seconds
        if ttl is None or ttl <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            expired = []
            for path, (_fd, _mm, created) in self._regions.items():
                if now - created <= ttl:
                    continue
                # W19（v3 第三波 FR-2 方向 A）：租约未到期的区域豁免回收——
                # 租约到期时钟与区域 TTL 时钟独立（取长者保护区域）。
                lease = self._leases.get(path)
                if lease is not None and lease[1] > now:
                    continue
                expired.append(path)
        for path in expired:
            if self.release(path):
                logger.info(
                    "TTL 回收共享内存区域: %s (TTL=%.1fs)", path, ttl
                )
        return len(expired)

    # ---------- 区域租约（W19 v3 第三波 FR-2 方向 A，PoC）----------

    def acquire_lease(self, key: str, ttl_ms: float) -> int:
        """在区域上登记租约，返回自增 lease_id。

        Args:
            key: 区域文件路径（须为本进程在册区域才有保护意义）。
            ttl_ms: 租约时长（毫秒）；到期后 TTL 回收恢复。

        同一区域重复 acquire 以最后一张租约为准（PoC 单租约模型，
        覆盖式登记，不维护多租约集合）。
        """
        expires_at = time.monotonic() + float(ttl_ms) / 1000.0
        with self._lock:
            self._next_lease_id += 1
            lease_id = self._next_lease_id
            self._leases[key] = (lease_id, expires_at)
        logger.debug("共享内存租约登记: %s (lease_id=%d, ttl_ms=%.0f)", key, lease_id, ttl_ms)
        return lease_id

    def release_leased(self, file_path: str, lease_id: int) -> bool:
        """校验租约归属后释放区域（lease_id 不符 → 拒绝，区域不动）。

        Returns:
            True=校验通过且区域命中回收；False=无在册租约 / 归属不符 /
            区域不存在（可能已被回收）。锁不可重入：归属校验与租约摘除
            在锁内完成，实际释放复用 :meth:`release`（锁外，与
            _reap_expired 同模式）。
        """
        with self._lock:
            lease = self._leases.get(file_path)
            if lease is None or lease[0] != lease_id:
                logger.warning(
                    "租约释放被拒（无在册租约或归属不符）: %s (lease_id=%s)",
                    file_path, lease_id,
                )
                return False
            del self._leases[file_path]
        return self.release(file_path)

    # ---------- 写出 ----------

    def write_array(self, array, dtype: str | None = None) -> SharedMemoryHandle:
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

    def write_bytes(self, data: bytes, dtype: str = "uint8", shape: tuple[int, ...] = ()) -> SharedMemoryHandle:
        """写入裸字节并给定 dtype/shape（用于非 numpy 来源）。

        W17：``dtype="bool_rle"`` 合法——data 须为 mask_codec 已编码的
        bool_rle 载荷，shape 为原掩码形状（serialization 内联超限时走此
        路径写出，避免二次编码）。
        """
        if dtype not in _DTYPE_MAP and dtype != "bool_rle":
            raise ValueError(
                f"不支持的 dtype: {dtype}，仅支持 {list(_DTYPE_MAP)} 与 bool_rle"
            )
        return self._write_raw(bytes(data), dtype, tuple(int(s) for s in shape))

    def write_mask_compact(self, masks) -> SharedMemoryHandle:
        """bool 掩码走 RLE 压缩写出（W6-T2，对标 CompactMask 游程编码）。

        dtype="bool_rle"（经 mask_codec 编码；read_array 自动解码）。
        W7 起 .NET SharedMemoryReader.ReadMasks 已支持 bool_rle 解码，
        gRPC Detect 默认走此路径（AVA_SHM_MASK_RLE=0 可退回 raw）。
        """
        import numpy as np

        arr = np.asarray(masks)
        if arr.dtype != np.bool_:
            arr = arr.astype(np.bool_)
        # L7（2026-10-05 一轮审查）：直连 core（W45 下沉后的正式入口），
        # 不再经 serving.mask_codec shim
        from core.mask_codec import encode_mask_rle

        payload = encode_mask_rle(arr)
        return self._write_raw(payload, "bool_rle", tuple(int(s) for s in arr.shape))

    def _write_raw(self, raw: bytes, dtype: str, shape: tuple[int, ...]) -> SharedMemoryHandle:
        # W17：先惰性回收超 TTL 区域（腾出登记槽位），再创建新区域
        self._reap_expired()

        name = f"ava_{uuid.uuid4().hex}.bin"
        path = str(self._base_dir / name)

        # 创建文件并预占空间（Windows 必须显式 O_BINARY：缺省文本模式会把
        # 二进制流中的 0x0A 翻译成 0x0D 0x0A，静默破坏数组数据——W3-T4 测试实测）
        flags = os.O_RDWR | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(path, flags, 0o600)
        try:
            # H4（2026-10-05 一轮审查）：os.write 单次调用可能部分写
            # （POSIX 下 >2GB 载荷或被信号中断时短写）——文件实际长度
            # < len(raw) 时 mmap(length) 超出文件尾，访问即 SIGBUS 直接
            # 杀进程（不可捕获）。循环写满（与 path_io.py:63-69 同款）。
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            # M4（2026-10-05 一轮审查）：fsync 改可配置——36MB 大图热路径
            # 每次落盘同步刷写吞吐显著下降；MMF 同机读取由页缓存保证一致，
            # 崩溃残留由 2 小时启动清扫兜底。默认关闭；特殊部署需要磁盘
            # 级持久性时 AVA_SHM_FSYNC=1 开启。
            if os.environ.get("AVA_SHM_FSYNC", "0") == "1":
                os.fsync(fd)
            length = len(raw)
            mm = mmap.mmap(fd, length, access=mmap.ACCESS_READ)
        except Exception:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(path)
            raise

        with self._lock:
            limit_hit = len(self._regions) >= self._max_regions
            if not limit_hit:
                self._regions[path] = (fd, mm, time.monotonic())
        if limit_hit:
            # 上限命中：回滚刚创建的映射与文件，拒绝分配（不得静默继续泄漏）
            self._discard_mapping(fd, mm, path)
            raise RuntimeError(
                f"共享内存区域登记已达上限: 当前 {len(self._regions)} 个 / "
                f"上限 {self._max_regions} 个。超过 TTL（"
                f"{_REGION_TTL_ENV}={self._region_ttl_seconds:.0f}s）的区域会在"
                f"下次写入前自动回收；若客户端持有未消费句柄请尽快读取，或显式"
                f"调用 ReleaseSharedMemory 回收，或调大环境变量 {_MAX_REGIONS_ENV}"
            )
        logger.debug("共享内存写出: %s (%d bytes, %s, shape=%s)", path, length, dtype, shape)
        return SharedMemoryHandle(
            file_path=path, offset=0, length=length, dtype=dtype, shape=shape
        )

    # ---------- 读入 ----------

    @staticmethod
    def _validate_range(offset: int, length: int, region_len: int, file_path: str) -> None:
        """H7（2026-10-05 一轮审查）：读区间合法性校验。

        负 offset 此前未被拒绝——mm[-1000:1000] 按 Python 尾部偏移语义
        静默拼接错位数据（检测结果错乱而非报错）。统一在入口显式拒绝。
        """
        if offset < 0 or length < 0:
            raise ValueError(
                f"共享内存读区间非法: offset={offset}, length={length}"
                f"（须 >= 0）: {file_path}"
            )
        if offset + length > region_len:
            raise ValueError(
                f"共享内存读区间越界: offset+length={offset + length}"
                f" > 区域长度 {region_len}: {file_path}"
            )

    def read_array(self, handle) -> numpy.ndarray:
        """按句柄读取并重建为 numpy 数组。

        适用于任意句柄（本进程或对端进程创建）。dtype=="bool_rle" 时
        经 mask_codec 解码还原 bool 掩码（W6-T2）。

        H6（2026-10-05 一轮审查）：本进程映射的读切片改在锁内完成拷贝
        ——此前锁内快照 entry 后锁外用 mm，并发线程 release 同区域时
        mm.close() 已执行，mm[...] 抛 ValueError 使请求崩溃（TOCTOU）。
        """
        import numpy as np

        h = _coerce_handle(handle)

        if h.dtype == "bool_rle":
            # L7：直连 core（同 write_mask_compact）
            from core.mask_codec import decode_mask_rle

            data = self.read_bytes(h)
            return decode_mask_rle(data, h.shape)

        if h.dtype not in _DTYPE_MAP:
            raise ValueError(f"不支持的 dtype: {h.dtype}，仅支持 {list(_DTYPE_MAP)}")

        np_dtype = np.dtype(_DTYPE_MAP[h.dtype])

        # 优先复用本进程已映射的区域，否则按路径打开对端创建的文件；
        # H6：锁内切片拷贝，防并发 release 关闭映射的竞态
        with self._lock:
            entry = self._regions.get(h.file_path)

        if entry is not None:
            _fd, mm, _created = entry
            with self._lock:
                # 双检：快照后到加锁前可能已被 release 摘除
                if self._regions.get(h.file_path) is not entry:
                    raise FileNotFoundError(
                        f"共享内存区域已被并发回收: {h.file_path}"
                    )
                self._validate_range(h.offset, h.length, mm.size(), h.file_path)
                data = bytes(mm[h.offset : h.offset + h.length])
        else:
            # S1：对端文件读取走白名单校验（本进程在册区域不受影响）
            data = _read_range_from_file(h.file_path, h.offset, h.length, base_dir=self._base_dir)

        arr = np.frombuffer(data, dtype=np_dtype)
        if h.shape:
            arr = arr.reshape(h.shape)
        return arr

    def read_bytes(self, handle) -> bytes:
        """按句柄读取为裸字节（H6：锁内拷贝防 TOCTOU）。"""
        h = _coerce_handle(handle)
        with self._lock:
            entry = self._regions.get(h.file_path)
            if entry is not None:
                _fd, mm, _created = entry
                self._validate_range(h.offset, h.length, mm.size(), h.file_path)
                return bytes(mm[h.offset : h.offset + h.length])
        return _read_range_from_file(h.file_path, h.offset, h.length, base_dir=self._base_dir)

    def read_range(self, file_path: str, offset: int, length: int) -> bytes:
        """按绝对区间读区域字节（W19 v3 第三波 FR-2 方向 B：FetchRegion 分块用）。

        优先复用本进程已映射区域，否则按路径读文件；文件不存在时抛
        FileNotFoundError（调用方据此 abort NOT_FOUND）。与
        :meth:`read_bytes` 的差别：入参是裸区间而非句柄，便于流式切块。

        S1（安全审查 2026-10-05）：对端文件读取经白名单校验——仅允许
        base_dir 下的 ava_*.bin；校验失败抛 ValueError（调用方 abort）。
        H6/H7：锁内拷贝 + 区间校验。
        """
        with self._lock:
            entry = self._regions.get(file_path)
            if entry is not None:
                _fd, mm, _created = entry
                self._validate_range(offset, length, mm.size(), file_path)
                return bytes(mm[offset : offset + length])
        return _read_range_from_file(file_path, offset, length, base_dir=self._base_dir)

    # ---------- 回收 ----------

    @staticmethod
    def _discard_mapping(fd: int, mm: mmap.mmap, path: str) -> None:
        """尽力关闭映射/描述符并删除文件（release 与上限拒绝路径共用）。"""
        with contextlib.suppress(BufferError, OSError):
            mm.close()
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(path)

    def release(self, file_path: str) -> bool:
        """释放指定区域（关闭映射并删除文件）。

        Returns:
            是否命中并回收了本进程创建的区域。对端创建的文件由其自行回收。
        """
        with self._lock:
            entry = self._regions.pop(file_path, None)
            # W19（v3 第三波 FR-2 方向 A）：区域回收时同步摘除在册租约
            # （幂等：release_leased 路径已先行删除，此处兜底其余回收路径）。
            self._leases.pop(file_path, None)

        if entry is None:
            # 非本进程创建：仅尝试删除文件（通常不应由本侧负责）
            logger.debug("release 未命中本进程区域: %s", file_path)
            return False

        fd, mm, _created = entry
        self._discard_mapping(fd, mm, file_path)
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

def _resolve_max_regions(explicit: int | None) -> int:
    """解析区域登记上限：构造参数 > 环境变量 AVA_SHM_MAX_REGIONS > 默认 64。"""
    if explicit is not None:
        if explicit < 1:
            raise ValueError(f"max_regions 必须 >= 1，收到 {explicit}")
        return int(explicit)
    raw = os.environ.get(_MAX_REGIONS_ENV)
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 不是整数，回退默认值 %d",
                _MAX_REGIONS_ENV, raw, _DEFAULT_MAX_REGIONS,
            )
    return _DEFAULT_MAX_REGIONS


def _resolve_region_ttl(explicit: float | None) -> float:
    """解析区域 TTL 秒（W17）：构造参数 > AVA_SHM_REGION_TTL_SECONDS > 默认 300。

    <= 0 表示关闭惰性回收（合法档位，非错误）。
    """
    if explicit is not None:
        return float(explicit)
    raw = os.environ.get(_REGION_TTL_ENV)
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 不是数值，回退默认值 %.1f 秒",
                _REGION_TTL_ENV, raw, _DEFAULT_REGION_TTL_SECONDS,
            )
    return _DEFAULT_REGION_TTL_SECONDS


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


def _read_range_from_file(file_path: str, offset: int, length: int, base_dir: Path | None = None) -> bytes:
    """从未映射的对端文件中读取指定区间。

    S1（安全审查 2026-10-05）：``base_dir`` 提供时执行白名单校验——
    仅允许读取 base_dir 下、文件名匹配 ava_*.bin 的区域文件，防止
    调用方（FetchRegion/read_* 系列经回环无鉴权 gRPC 暴露）把本函数
    当作任意文件读取原语。校验失败抛 ValueError。
    """
    if base_dir is not None and not _shm_path_allowed(file_path, base_dir):
        logger.warning(
            "拒绝读取白名单外的共享内存路径: %s (base_dir=%s)", file_path, base_dir
        )
        raise ValueError(
            f"共享内存路径不在允许目录内: {file_path}"
        )
    with open(file_path, "rb") as f:
        if offset:
            f.seek(offset)
        return f.read(length)


__all__ = ["SharedMemoryHandle", "SharedMemoryManager"]
