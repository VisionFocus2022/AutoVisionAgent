"""AutoVisionAgent 对外服务层（gRPC + 共享内存）。

通过 gRPC 暴露 :class:`VisionModelDispatcher` 的检测能力，并用文件映射
共享内存在同机进程间零拷贝传递大块二进制数据（大图、掩码、关键点）。

快速开始::

    # 1. 启动服务
    python -m serving --host 127.0.0.1 --port 50051

    # 2. 客户端（Python 自测 / .NET VisionAgent.Shared）按 proto 调用
    from serving.proto import autovisionagent_pb2 as pb
    ...

模块组成
--------
- :mod:`serving.proto`         : protobuf 契约 + 生成代码
- :mod:`serving.shared_memory` : 文件映射 MMF 管理器
- :mod:`serving.serialization` : DetectionResult ↔ proto / numpy ↔ shm
- :mod:`serving.server`        : gRPC 服务实现（封装 VisionModelDispatcher）
"""
from serving.server import AutoVisionAgentServicer, create_server, serve
from serving.shared_memory import SharedMemoryHandle, SharedMemoryManager

__all__ = [
    "AutoVisionAgentServicer",
    "create_server",
    "serve",
    "SharedMemoryHandle",
    "SharedMemoryManager",
]
