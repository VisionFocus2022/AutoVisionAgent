using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Grpc.Core;
using Grpc.Net.Client;
using VisionAgent.Shared.Interfaces.Vision;
using VisionAgent.Shared.Models.Vision;
using VisionAgent.Shared.Protos.AutoVisionAgent;

namespace VisionAgent.Shared.Services.Vision
{
    /// <summary>
    /// AutoVisionAgent gRPC + 共享内存 客户端实现。
    /// 通过 gRPC 调用 Python serving 端（<c>serving.server</c>）的检测能力，
    /// 并用文件映射共享内存在同机进程间零拷贝传递大图 / 掩码 / 关键点。
    /// </summary>
    /// <remarks>
    /// 启动 Python 服务：<c>python -m serving --host 127.0.0.1 --port 50051</c>
    /// 本端连接：<c>new AutoVisionAgentClient("http://127.0.0.1:50051")</c>
    /// </remarks>
    public sealed class AutoVisionAgentClient : IAutoVisionAgentClient, IDisposable
    {
        private readonly GrpcChannel _channel;
        private readonly AutoVisionAgentService.AutoVisionAgentServiceClient _stub;
        private readonly SharedMemoryReader _shmReader;
        private readonly string _shmDir;

        /// <param name="address">gRPC 服务地址，如 <c>http://127.0.0.1:50051</c>。</param>
        /// <param name="shmReader">共享内存读取器；默认新建。</param>
        public AutoVisionAgentClient(string address, SharedMemoryReader? shmReader = null)
            : this(GrpcChannel.ForAddress(address), shmReader) { }

        /// <summary>
        /// 内部构造函数：允许测试注入预构建的 <see cref="GrpcChannel"/>
        /// （如 in-process TestServer），避免占用真实端口。
        /// </summary>
        internal AutoVisionAgentClient(GrpcChannel channel, SharedMemoryReader? shmReader = null)
        {
            _channel = channel;
            _stub = new AutoVisionAgentService.AutoVisionAgentServiceClient(_channel);
            _shmReader = shmReader ?? new SharedMemoryReader();
            _shmDir = Path.Combine(Path.GetTempPath(), "autovisionagent_shm");
            Directory.CreateDirectory(_shmDir);
        }

        // --------------------------------- 元数据 -------------------------------- #

        public PongResponse Ping()
        {
            return _stub.Ping(new PingRequest());
        }

        public IReadOnlyList<TaskInfo> ListTasks()
        {
            return _stub.ListTasks(new ListTasksRequest()).Tasks.ToList();
        }

        public TaskInfo GetTaskInfo(string task)
        {
            return _stub.GetTaskInfo(new GetTaskInfoRequest { Task = task });
        }

        // ------------------------------- 模型生命周期 ----------------------------- #

        public (bool Success, string Error) LoadModel(string task, string weightsPath, string device = "cuda")
        {
            var resp = _stub.LoadModel(new LoadModelRequest
            {
                Task = task,
                WeightsPath = weightsPath,
                Device = device,
            });
            return (resp.Success, resp.Error);
        }

        public (bool Success, string Error) UnloadModel(string task)
        {
            var resp = _stub.UnloadModel(new UnloadModelRequest { Task = task });
            return (resp.Success, resp.Error);
        }

        // ----------------------------------- 推理 -------------------------------- #

        public DetectionResult? Detect(
            string task,
            byte[] imageBytes,
            string mode = "auto",
            float threshold = 0.5f,
            IList<string>? labels = null,
            IList<string>? prompts = null)
        {
            var req = BuildRequest(task, mode, threshold, labels, prompts);
            req.ImageBytes = Google.Protobuf.ByteString.CopyFrom(imageBytes);
            return CallDetect(req);
        }

        public DetectionResult? DetectFromFile(
            string task,
            string imagePath,
            string mode = "auto",
            float threshold = 0.5f,
            IList<string>? labels = null,
            IList<string>? prompts = null)
        {
            var req = BuildRequest(task, mode, threshold, labels, prompts);
            req.ImagePath = imagePath;
            return CallDetect(req);
        }

        public DetectionResult? DetectViaSharedMemory(
            string task,
            SharedMemoryHandle imageShm,
            string mode = "auto",
            float threshold = 0.5f,
            IList<string>? labels = null,
            IList<string>? prompts = null)
        {
            var req = BuildRequest(task, mode, threshold, labels, prompts);
            req.ImageShm = imageShm;
            return CallDetect(req);
        }

        // ------------------------------ 共享内存写出 ------------------------------ #

        public SharedMemoryHandle WriteImageToSharedMemory(byte[,,] imageRgb)
        {
            if (imageRgb is null) throw new ArgumentNullException(nameof(imageRgb));
            int h = imageRgb.GetLength(0);
            int w = imageRgb.GetLength(1);
            int c = imageRgb.GetLength(2);

            // 拍平为行优先字节序，与 Python numpy C-order 对齐
            var bytes = new byte[h * w * c];
            int idx = 0;
            for (int i = 0; i < h; i++)
                for (int j = 0; j < w; j++)
                    for (int t = 0; t < c; t++)
                        bytes[idx++] = imageRgb[i, j, t];

            var path = Path.Combine(_shmDir, $"ava_{Guid.NewGuid():N}.bin");
            File.WriteAllBytes(path, bytes);

            return new SharedMemoryHandle
            {
                FilePath = path,
                Offset = 0,
                Length = bytes.Length,
                Dtype = "uint8",
            };
        }

        public (bool Success, string Error) ReleaseSharedMemory(string filePath)
        {
            try
            {
                var resp = _stub.ReleaseSharedMemory(new ReleaseSharedMemoryRequest { FilePath = filePath });
                // 服务端仅回收它自己创建的区域；本端创建的文件由本端删除
                if (File.Exists(filePath))
                {
                    try { File.Delete(filePath); } catch { /* 忽略 */ }
                }
                return (resp.Success, resp.Error);
            }
            catch (RpcException ex)
            {
                return (false, ex.Message);
            }
        }

        // ---------------------------------- 内部 --------------------------------- #

        private static DetectRequest BuildRequest(
            string task, string mode, float threshold,
            IList<string>? labels, IList<string>? prompts)
        {
            var req = new DetectRequest
            {
                Task = task,
                Mode = mode,
                Threshold = threshold,
            };
            if (labels is not null) req.Labels.AddRange(labels);
            if (prompts is not null) req.Prompts.AddRange(prompts);
            return req;
        }

        private DetectionResult? CallDetect(DetectRequest request)
        {
            DetectResponse resp = _stub.Detect(request);
            if (!resp.Success)
                throw new InvalidOperationException(
                    string.IsNullOrEmpty(resp.Error) ? "Detect 失败" : resp.Error);

            return DetectionResultMapper.ToDetectionResult(resp.Result, _shmReader);
        }

        public void Dispose()
        {
            _channel.Dispose();
            _shmReader.Dispose();
        }
    }
}
