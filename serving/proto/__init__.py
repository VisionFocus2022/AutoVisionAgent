"""AutoVisionAgent 对外 gRPC 契约（protobuf 生成代码）。

生成方式（重新生成后需保持 autovisionagent_pb2_grpc.py 的包内相对导入修正）：

    python -m grpc_tools.protoc -I serving/proto \
        --python_out=serving/proto \
        --grpc_python_out=serving/proto \
        serving/proto/autovisionagent.proto
"""
from serving.proto import autovisionagent_pb2 as _pb2

# 常用消息类型便捷导出
SharedMemoryHandle = _pb2.SharedMemoryHandle
PingRequest = _pb2.PingRequest
PongResponse = _pb2.PongResponse
ListTasksRequest = _pb2.ListTasksRequest
ListTasksResponse = _pb2.ListTasksResponse
TaskInfo = _pb2.TaskInfo
GetTaskInfoRequest = _pb2.GetTaskInfoRequest
LoadModelRequest = _pb2.LoadModelRequest
LoadModelResponse = _pb2.LoadModelResponse
UnloadModelRequest = _pb2.UnloadModelRequest
UnloadModelResponse = _pb2.UnloadModelResponse
DetectRequest = _pb2.DetectRequest
DetectResponse = _pb2.DetectResponse
DetectionResultProto = _pb2.DetectionResultProto
ReleaseSharedMemoryRequest = _pb2.ReleaseSharedMemoryRequest
ReleaseSharedMemoryResponse = _pb2.ReleaseSharedMemoryResponse

__all__ = [
    "SharedMemoryHandle",
    "PingRequest", "PongResponse",
    "ListTasksRequest", "ListTasksResponse", "TaskInfo",
    "GetTaskInfoRequest",
    "LoadModelRequest", "LoadModelResponse",
    "UnloadModelRequest", "UnloadModelResponse",
    "DetectRequest", "DetectResponse", "DetectionResultProto",
    "ReleaseSharedMemoryRequest", "ReleaseSharedMemoryResponse",
]
