"""AutoVisionAgent gRPC 服务实现。

将 :class:`industrial_vision_platform.vision_dispatcher.VisionModelDispatcher`
的 Python 函数能力，通过 gRPC + 共享内存对外暴露，供 VisionAgent.Shared
（.NET）等外部进程调用模型检测结果。

启动::

    python -m serving                  # 默认 127.0.0.1:50051
    python -m serving --host 127.0.0.1 --port 50051 --max-workers 8

注意：本服务无 TLS/token（见 docs/adr/0001-serving-loopback.md），
默认且推荐的监听地址是回环 127.0.0.1；跨机暴露需自行承担安全风险。
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from concurrent import futures
from typing import Any, Iterator, Optional

import grpc

from core.interfaces_supervised import TaskType
from serving.proto import autovisionagent_pb2 as pb
from serving.proto import autovisionagent_pb2_grpc as pb_grpc
from serving.serialization import (
    decode_request_image,
    detection_result_to_proto,
    str_to_task_type,
)
from serving.shared_memory import SharedMemoryManager

logger = logging.getLogger(__name__)

_SERVER_VERSION = "autovisionagent-serving/1.0"

# P2-9（W17 簇C）：回环地址白名单——非回环绑定须在绑定前告警（ADR-0001）
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# W19（v3 第三波 FR-2 方向 B，PoC）：FetchRegion 服务端流分块大小（1 MiB）
_FETCH_CHUNK_BYTES = 1024 * 1024


class AutoVisionAgentServicer(pb_grpc.AutoVisionAgentServiceServicer):
    """gRPC Servicer：把 RPC 转发到 VisionModelDispatcher 单例。"""

    def __init__(
        self,
        dispatcher: Any,
        shm: Optional[SharedMemoryManager] = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._shm = shm or SharedMemoryManager()

    # ----------------------------- 健康 & 元数据 ---------------------------- #

    def Ping(self, request: pb.PingRequest, context: grpc.ServicerContext) -> pb.PongResponse:
        loaded: list[str] = []
        ready = self._dispatcher is not None
        if ready:
            try:
                loaded = list(getattr(self._dispatcher, "loaded_tasks", []) or [])
            except Exception:
                loaded = []
        return pb.PongResponse(
            server_version=_SERVER_VERSION,
            dispatcher_ready=ready,
            loaded_tasks=loaded,
        )

    def ListTasks(self, request: pb.ListTasksRequest, context: grpc.ServicerContext) -> pb.ListTasksResponse:
        try:
            tasks = self._dispatcher.list_all_tasks()
        except Exception as e:
            # W14-C3（P2-13）：整体失败返回空列表与"真无任务"在协议上不可区分，
            # 必须落 ERROR 让服务端可辨识（客户端侧结合 Ping.dispatcher_ready 判别）。
            logger.error("ListTasks 失败（返回空列表）: %s", e, exc_info=True)
            return pb.ListTasksResponse()
        resp = pb.ListTasksResponse()
        for t in tasks:
            info = resp.tasks.add(
                task=str(t.get("task", "")),
                paradigm=str(t.get("paradigm", "")),
                requires_training=bool(t.get("requires_training", False)),
            )
            # loaded 状态需查 dispatcher
            try:
                info.loaded = self._dispatcher.get_task_info(str(t.get("task", ""))).get("loaded", False)
            except Exception:
                info.loaded = False
        return resp

    def GetTaskInfo(self, request: pb.GetTaskInfoRequest, context: grpc.ServicerContext) -> pb.TaskInfo:
        try:
            d = self._dispatcher.get_task_info(request.task)
        except Exception as e:
            logger.warning("GetTaskInfo(%s) 失败: %s", request.task, e)
            d = {"task": request.task, "paradigm": "unknown", "loaded": False, "requires_training": False}
        return pb.TaskInfo(
            task=str(d.get("task", request.task)),
            paradigm=str(d.get("paradigm", "")),
            loaded=bool(d.get("loaded", False)),
            requires_training=bool(d.get("requires_training", False)),
        )

    # ------------------------------- 模型生命周期 ---------------------------- #

    def LoadModel(self, request: pb.LoadModelRequest, context: grpc.ServicerContext) -> pb.LoadModelResponse:
        try:
            task = str_to_task_type(request.task)
            device = request.device or "cuda"
            self._dispatcher.load_supervised(task, request.weights_path, device=device)
            return pb.LoadModelResponse(success=True)
        except Exception as e:
            logger.exception("LoadModel 失败 task=%s", request.task)
            return pb.LoadModelResponse(success=False, error=str(e))

    def UnloadModel(self, request: pb.UnloadModelRequest, context: grpc.ServicerContext) -> pb.UnloadModelResponse:
        try:
            task = str_to_task_type(request.task)
            # VisionModelDispatcher 没有公开 unload 单任务接口，借助 registry 释放缓存
            from models.supervised.registry import get_default_registry
            get_default_registry().clear_cache(task)
            return pb.UnloadModelResponse(success=True)
        except Exception as e:
            logger.exception("UnloadModel 失败 task=%s", request.task)
            return pb.UnloadModelResponse(success=False, error=str(e))

    # ---------------------------------- 推理 -------------------------------- #

    def Detect(self, request: pb.DetectRequest, context: grpc.ServicerContext) -> pb.DetectResponse:
        try:
            image = decode_request_image(request, self._shm)
        except Exception as e:
            logger.warning("图像解码失败: %s", e)
            return pb.DetectResponse(success=False, error=f"图像解码失败: {e}")

        # 组装 kwargs
        kwargs: dict[str, Any] = {}
        if request.threshold:
            kwargs["threshold"] = float(request.threshold)
        if request.labels:
            kwargs["labels"] = list(request.labels)
        if request.prompts:
            kwargs["prompts"] = list(request.prompts)
        mode = request.mode or "auto"
        task = request.task or "det"

        try:
            result = self._dispatcher.infer(task, image, mode=mode, **kwargs)
        except Exception as e:
            logger.exception("推理失败 task=%s", task)
            return pb.DetectResponse(success=False, error=str(e))

        try:
            proto = detection_result_to_proto(result, self._shm)
        except Exception as e:
            logger.exception("结果序列化失败")
            return pb.DetectResponse(success=False, error=f"结果序列化失败: {e}")

        return pb.DetectResponse(success=True, result=proto)

    # ------------------------------ 共享内存回收 ----------------------------- #

    def ReleaseSharedMemory(
        self, request: pb.ReleaseSharedMemoryRequest, context: grpc.ServicerContext
    ) -> pb.ReleaseSharedMemoryResponse:
        try:
            # W19（v3 第三波 FR-2 方向 A，PoC）：非 0 lease_id → 校验归属后
            # 释放；错误租约拒绝且区域不动。默认（0，无租约）路径不变。
            if request.lease_id:
                ok = self._shm.release_leased(request.file_path, int(request.lease_id))
            else:
                ok = self._shm.release(request.file_path)
            if not ok:
                # W17（v3 P1-1 附带）：未命中本进程区域不得假报成功——旧行为
                # 恒 success=True，客户端把"什么都没回收"当成功 ACK，与泄漏
                # 互为盲区。未命中多为：路径错 / 已回收 / 对端创建的文件 /
                # （W19）租约归属不符。
                logger.warning(
                    "ReleaseSharedMemory 未命中或被拒: %s (lease_id=%d)",
                    request.file_path, request.lease_id,
                )
                return pb.ReleaseSharedMemoryResponse(
                    success=False,
                    error=(
                        "区域不存在、非本服务创建或租约归属不符"
                        f"（lease_id={request.lease_id}）：{request.file_path}"
                    ),
                )
            return pb.ReleaseSharedMemoryResponse(success=True)
        except Exception as e:
            # W14-C3（P2-13）：共享内存泄漏排查依赖服务端日志（与客户端
            # 空吞 catch 互为盲区），此处必须留痕。
            logger.warning(
                "ReleaseSharedMemory(%s) 失败: %s", request.file_path, e, exc_info=True
            )
            return pb.ReleaseSharedMemoryResponse(success=False, error=str(e))

    # ------------------- 大区域流式拉取（W19 FR-2 方向 B PoC） ------------------- #

    def FetchRegion(
        self, request: pb.SharedMemoryHandle, context: grpc.ServicerContext
    ) -> Iterator[pb.ArrayChunk]:
        """按句柄把共享内存区域字节以 1 MiB ArrayChunk 流式回传。

        供无法做同机文件映射的消费端（跨机/受限沙箱）取回大数组；
        区域不存在/已被回收 → context.abort(NOT_FOUND)。生产路径
        未启用（serialization 默认不产生本调用，ADR-0002）。
        """
        end = int(request.offset) + int(request.length)
        pos = int(request.offset)
        while pos < end:
            n = min(_FETCH_CHUNK_BYTES, end - pos)
            try:
                data = self._shm.read_range(request.file_path, pos, n)
            except FileNotFoundError:
                context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"共享内存区域不存在或已被回收: {request.file_path}",
                )
                return  # 静态检查友好；abort 已抛出终止异常
            if len(data) != n:
                # 短读：文件被截断（异常态），按区域已损坏终止
                context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"共享内存区域读取短块（期望 {n}，实得 {len(data)}）: {request.file_path}",
                )
                return
            # W19 验证修正：offset 取本块起始位移（首块为 0）——与 proto
            # 注释/重组惯例一致（消费端 handle.offset+chunk.offset 定位）
            rel = pos - int(request.offset)
            pos += n
            yield pb.ArrayChunk(data=data, offset=rel, last=pos >= end)


# ------------------------------ 服务启动入口 ------------------------------- #

# P2-20：serving 独立进程此前仅 console 日志（basicConfig），脱离 GUI 运行时
# 日志随终端关闭消失（审查 v2 实测：serving/*.py 无一处 FileHandler）。
# RotatingFileHandler 挂 root——shared_memory 等子 logger 经传播统一落盘。

# setup_file_logging 挂载标记：幂等摘除旧 handler 时识别"自己挂的"用
_SERVING_FILE_HANDLER_MARK = "_ava_serving_file"


def setup_file_logging(
    log_dir: str,
    filename: str = "serving.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Handler:
    """挂 RotatingFileHandler 到 root logger（P2-20：独立进程文件日志）。

    - 路径参数化（目录/文件名/单文件上限/备份数），测试与嵌入方可注入；
    - 幂等：先摘除并关闭此前由本函数挂载的 handler 再挂新——重复调用
      不会重复挂载、不会双写；
    - 仅允许在 serve() 入口调用（python -m serving 路径）；模块 import
      期零副作用（见 test_import_serving_server_adds_no_root_handler）。

    Args:
        log_dir: 日志目录（不存在则创建）。
        filename: 日志文件名。
        max_bytes: 单文件轮转上限（字节）。
        backup_count: 轮转保留的备份份数。

    Returns:
        挂载的 RotatingFileHandler（调用方可断言/摘除）。
    """
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger()
    for old in [
        h for h in root.handlers if getattr(h, _SERVING_FILE_HANDLER_MARK, False)
    ]:
        root.removeHandler(old)
        old.close()
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, filename),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    setattr(handler, _SERVING_FILE_HANDLER_MARK, True)
    root.addHandler(handler)
    return handler


def _resolve_log_dir() -> str:
    """日志目录解析：与 GUI（gui/main.setup_logging）同源——core.config
    LoggingConfig.log_dir，配置不可用则回退 ./logs（GUI 同款兜底）。

    W23（v4 P2-1c）：AVA_LOG_DIR 显式指定时优先（测试态隔离约定，与
    gui/main.setup_logging 一致；生产不设 env 行为不变）。
    """
    env_dir = os.environ.get("AVA_LOG_DIR")
    if env_dir:
        return env_dir
    try:
        from core.config import get_config

        return str(get_config().logging.log_dir)
    except (AttributeError, ImportError, TypeError, ValueError):
        return "./logs"


def create_server(
    host: str = "127.0.0.1",
    port: int = 50051,
    max_workers: int = 8,
    dispatcher: Any = None,
    shm: Optional[SharedMemoryManager] = None,
) -> grpc.Server:
    """构造并返回 gRPC server（未启动）。

    Args:
        dispatcher: 注入的 VisionModelDispatcher；默认用全局单例。
        shm: 注入的 SharedMemoryManager；默认新建。
    """
    if dispatcher is None:
        # 延迟导入，避免 dispatcher 依赖（如 torch）未就绪时影响模块加载
        from industrial_vision_platform.vision_dispatcher import get_dispatcher
        dispatcher = get_dispatcher()

    if host not in _LOOPBACK_HOSTS:
        # P2-9（W17 簇C）：绑定前告警——无 TLS/token 的 gRPC 一旦非回环监听，
        # 即对整个网段裸奔（任意客户端可加载模型/触发推理），须显式提醒。
        logger.warning(
            "非回环绑定: %s:%d —— 本服务无 TLS/token 鉴权，非回环监听会把 gRPC "
            "接口（加载模型/触发推理/读写共享内存）暴露给外部网络；请确认网络"
            "边界与访问来源，或参考 ADR-0001（docs/adr/0001-serving-loopback.md）"
            "改用回环地址 + 反向代理方案",
            host,
            port,
        )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    pb_grpc.add_AutoVisionAgentServiceServicer_to_server(
        AutoVisionAgentServicer(dispatcher, shm), server
    )
    server.add_insecure_port(f"{host}:{port}")
    return server


def serve(
    host: str = "127.0.0.1",
    port: int = 50051,
    max_workers: int = 8,
    log_dir: Optional[str] = None,
) -> None:
    """阻塞运行 gRPC server。

    Args:
        host/port/max_workers: 监听地址与线程池规格。
        log_dir: 文件日志目录；None 时经 :func:`_resolve_log_dir`（与 GUI
            同源的 logs/ 目录）。可由测试/嵌入方注入。
    """
    logging.basicConfig(
        level=os.environ.get("AVA_SERVING_LOG", "INFO"),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        # P2-20：独立进程文件日志（console 之外留持久轨迹）。文件日志失败
        # 不得阻断服务启动，但必须留痕（不得静默吞——W14 静默 except 教训）。
        handler = setup_file_logging(log_dir or _resolve_log_dir())
        logger.info("文件日志已启用: %s", handler.baseFilename)
    except OSError as e:
        logger.warning("文件日志初始化失败，仅以 console 日志运行: %s", e)
    server = create_server(host, port, max_workers)
    server.start()
    logger.info("AutoVisionAgent gRPC 服务已启动: %s:%d (max_workers=%d)", host, port, max_workers)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止...")
        server.stop(grace=3)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m serving",
        description="AutoVisionAgent gRPC + 共享内存对外服务",
    )
    p.add_argument("--host", default=os.environ.get("AVA_HOST", "127.0.0.1"),
                   help="监听地址（默认 127.0.0.1，环境变量 AVA_HOST）")
    p.add_argument("--port", type=int, default=int(os.environ.get("AVA_PORT", "50051")),
                   help="监听端口（默认 50051，环境变量 AVA_PORT）")
    p.add_argument("--max-workers", type=int, default=int(os.environ.get("AVA_MAX_WORKERS", "8")),
                   help="工作线程数（默认 8）")
    return p


__all__ = ["AutoVisionAgentServicer", "create_server", "serve", "setup_file_logging"]
