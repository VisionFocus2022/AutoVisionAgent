using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Grpc.Core;
using Grpc.Net.Client;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using VisionAgent.Shared.Enums.Vision;
using VisionAgent.Shared.Protos.AutoVisionAgent;
using VisionAgent.Shared.Services.Vision;
using Xunit;

namespace VisionAgent.Shared.Tests.Vision
{
    /// <summary>
    /// <see cref="AutoVisionAgentClient"/> 端到端单元测试。
    /// 用 in-process <see cref="TestServer"/> 承载一个 fake gRPC servicer，
    /// 真实客户端经 <see cref="GrpcChannel"/>（绑定 TestServer 的 HttpClient）调用，
    /// 验证请求编排与响应解析的完整链路（不占用真实端口、不依赖 Python serving）。
    /// </summary>
    public sealed class AutoVisionAgentClientTests : IAsyncLifetime, IDisposable
    {
        private IWebHost? _host;
        private FakeServicer _fake = new();
        private AutoVisionAgentClient? _client;

        public async Task InitializeAsync()
        {
            // 允许明文 HTTP/2（TestServer 场景）
            AppContext.SetSwitch("System.Net.Http.SocketsHttpHandler.Http2UnencryptedSupport", true);

            _fake = new FakeServicer();
            _host = new WebHostBuilder()
                .UseTestServer()
                .ConfigureServices(services =>
                {
                    services.AddGrpc();
                    services.AddSingleton(_fake);
                })
                .Configure(app =>
                {
                    app.UseRouting();
                    app.UseEndpoints(endpoints => endpoints.MapGrpcService<FakeServicer>());
                })
                .Build();
            await _host.StartAsync();

            var http = _host.GetTestClient();
            var channel = GrpcChannel.ForAddress("http://localhost", new GrpcChannelOptions
            {
                HttpClient = http,
            });
            _client = new AutoVisionAgentClient(channel);
        }

        public async Task DisposeAsync()
        {
            _client?.Dispose();
            if (_host is not null)
            {
                await _host.StopAsync();
                _host.Dispose();
            }
        }

        public void Dispose() { /* 异步清理在 DisposeAsync 完成 */ }

        // ------------------------------------- 元数据 ---------------------------------- //

        [Fact]
        public void Ping_Returns_FakeVersion()
        {
            var pong = _client!.Ping();

            Assert.Equal("fake/1.0", pong.ServerVersion);
            Assert.True(pong.DispatcherReady);
        }

        [Fact]
        public void ListTasks_Returns_FakeTasks()
        {
            var tasks = _client!.ListTasks();

            Assert.NotEmpty(tasks);
            Assert.Contains(tasks, t => t.Task == "det" && t.Paradigm == "supervised");
        }

        [Fact]
        public void GetTaskInfo_Returns_FakeInfo()
        {
            var info = _client!.GetTaskInfo("det");

            Assert.Equal("det", info.Task);
            Assert.True(info.RequiresTraining);
        }

        // ---------------------------------- 模型生命周期 --------------------------------- //

        [Fact]
        public void LoadModel_Success_ReturnsTrue()
        {
            _fake.LoadModelResponse = new LoadModelResponse { Success = true };

            var (ok, err) = _client!.LoadModel("det", @"D:\weights\best.pt", "cuda");

            Assert.True(ok);
            Assert.Equal(string.Empty, err);
            Assert.Equal("det", _fake.LastLoadModelRequest?.Task);
            Assert.Equal(@"D:\weights\best.pt", _fake.LastLoadModelRequest?.WeightsPath);
            Assert.Equal("cuda", _fake.LastLoadModelRequest?.Device);
        }

        [Fact]
        public void LoadModel_Failure_PropagatesError()
        {
            _fake.LoadModelResponse = new LoadModelResponse { Success = false, Error = "权重文件不存在" };

            var (ok, err) = _client!.LoadModel("det", "/missing.pt");

            Assert.False(ok);
            Assert.Equal("权重文件不存在", err);
        }

        [Fact]
        public void UnloadModel_ReturnsSuccess()
        {
            _fake.UnloadModelResponse = new UnloadModelResponse { Success = true };

            var (ok, _) = _client!.UnloadModel("det");

            Assert.True(ok);
            Assert.Equal("det", _fake.LastUnloadModelRequest?.Task);
        }

        // ------------------------------------- 推理 ----------------------------------- //

        [Fact]
        public async Task Detect_WithImageBytes_SendsBytes_AndParsesResult()
        {
            var imageBytes = new byte[] { 0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3 }; // 伪 JPEG 头
            await Task.Yield(); // 消除 warning，无实际意义

            var result = _client!.Detect("det", imageBytes, mode: "supervised", threshold: 0.5f);

            // 请求侧：fake 收到的 image_bytes 与发送一致
            Assert.NotNull(_fake.LastDetectRequest);
            Assert.Equal(imageBytes, _fake.LastDetectRequest!.ImageBytes.ToByteArray());
            Assert.Equal("det", _fake.LastDetectRequest.Task);
            Assert.Equal("supervised", _fake.LastDetectRequest.Mode);
            Assert.Equal(0.5f, _fake.LastDetectRequest.Threshold);

            // 响应侧：客户端按 fake 默认响应解析为 DetectionResult
            Assert.NotNull(result);
            Assert.Equal(DetectionTaskType.Det, result!.TaskType);
            Assert.Equal(0.95, result.Score);
            Assert.Single(result.Labels);
            Assert.Equal("defect", result.Labels[0]);
            Assert.NotNull(result.Boxes);
            Assert.Equal(1, result.Boxes!.GetLength(0));
            Assert.Equal(10.0, result.Boxes[0, 0]);
            Assert.Equal(40.0, result.Boxes[0, 3]);
            Assert.Equal("fake", result.Extra["source"]);
        }

        [Fact]
        public void Detect_WithLabels_ForwardsLabels()
        {
            _client!.Detect("det", new byte[] { 1, 2 }, labels: new[] { "a", "b" });

            Assert.Equal(new[] { "a", "b" }, _fake.LastDetectRequest!.Labels.ToArray());
        }

        [Fact]
        public void Detect_FromFile_ForwardsImagePath()
        {
            var path = @"C:\images\sample.png";

            _client!.DetectFromFile("det", path);

            Assert.Equal(path, _fake.LastDetectRequest!.ImagePath);
        }

        [Fact]
        public void Detect_ViaSharedMemory_WritesFile_AndForwardsHandle()
        {
            // 2×2×3 图像
            var img = new byte[,,]
            {
                { { 1, 2, 3 }, { 4, 5, 6 } },
                { { 7, 8, 9 }, { 10, 11, 12 } },
            };

            var handle = _client!.WriteImageToSharedMemory(img);

            try
            {
                Assert.True(File.Exists(handle.FilePath));
                Assert.Equal(12, handle.Length);
                Assert.Equal("uint8", handle.Dtype);

                _client.DetectViaSharedMemory("det", handle);

                // fake 收到的句柄路径/长度与客户端写出一致
                Assert.Equal(handle.FilePath, _fake.LastDetectRequest!.ImageShm.FilePath);
                Assert.Equal(12, _fake.LastDetectRequest.ImageShm.Length);

                // 写出的文件内容与原图行优先字节序一致
                var written = File.ReadAllBytes(handle.FilePath);
                Assert.Equal(new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 }, written);
            }
            finally
            {
                if (File.Exists(handle.FilePath)) File.Delete(handle.FilePath);
            }
        }

        [Fact]
        public void Detect_Failure_Throws_WithError()
        {
            _fake.DetectResponder = () => new DetectResponse { Success = false, Error = "引擎未加载" };

            var ex = Assert.Throws<InvalidOperationException>(() => _client!.Detect("det", new byte[] { 1 }));
            Assert.Contains("引擎未加载", ex.Message);
        }

        // ---------------------------------- 共享内存回收 --------------------------------- //

        [Fact]
        public void ReleaseSharedMemory_CallsServer_AndReturnsSuccess()
        {
            _fake.ReleaseShmResponse = new ReleaseSharedMemoryResponse { Success = true };

            var (ok, _) = _client!.ReleaseSharedMemory("C:\\tmp\\ava_x.bin");

            Assert.True(ok);
            Assert.Equal("C:\\tmp\\ava_x.bin", _fake.LastReleaseShmRequest?.FilePath);
        }

        // --------------------------------- Fake servicer -------------------------------- //

        /// <summary>内存内 gRPC 服务实现：记录请求、返回可配置的固定响应。</summary>
        private sealed class FakeServicer : AutoVisionAgentService.AutoVisionAgentServiceBase
        {
            public PongResponse PingResponse { get; set; } = new()
            {
                ServerVersion = "fake/1.0",
                DispatcherReady = true,
            };

            public LoadModelResponse LoadModelResponse { get; set; } = new() { Success = true };
            public LoadModelRequest? LastLoadModelRequest { get; private set; }

            public UnloadModelResponse UnloadModelResponse { get; set; } = new() { Success = true };
            public UnloadModelRequest? LastUnloadModelRequest { get; private set; }

            public Func<DetectResponse>? DetectResponder { get; set; }
            public DetectRequest? LastDetectRequest { get; private set; }

            public ReleaseSharedMemoryResponse ReleaseShmResponse { get; set; } = new() { Success = true };
            public ReleaseSharedMemoryRequest? LastReleaseShmRequest { get; private set; }

            public override Task<PongResponse> Ping(PingRequest request, ServerCallContext context)
                => Task.FromResult(PingResponse);

            public override Task<ListTasksResponse> ListTasks(ListTasksRequest request, ServerCallContext context)
            {
                // 镜像 Python serving 诚实契约（W14 P2-8）：不再返回 zero_shot（无内置实现）
                var resp = new ListTasksResponse();
                resp.Tasks.Add(new TaskInfo { Task = "det", Paradigm = "supervised", RequiresTraining = true });
                return Task.FromResult(resp);
            }

            public override Task<TaskInfo> GetTaskInfo(GetTaskInfoRequest request, ServerCallContext context)
                => Task.FromResult(new TaskInfo
                {
                    Task = request.Task,
                    Paradigm = "supervised",
                    RequiresTraining = true,
                });

            public override Task<LoadModelResponse> LoadModel(LoadModelRequest request, ServerCallContext context)
            {
                LastLoadModelRequest = request;
                return Task.FromResult(LoadModelResponse);
            }

            public override Task<UnloadModelResponse> UnloadModel(UnloadModelRequest request, ServerCallContext context)
            {
                LastUnloadModelRequest = request;
                return Task.FromResult(UnloadModelResponse);
            }

            public override Task<DetectResponse> Detect(DetectRequest request, ServerCallContext context)
            {
                LastDetectRequest = request;
                return Task.FromResult(DetectResponder?.Invoke() ?? DefaultDetectResponse());
            }

            public override Task<ReleaseSharedMemoryResponse> ReleaseSharedMemory(
                ReleaseSharedMemoryRequest request, ServerCallContext context)
            {
                LastReleaseShmRequest = request;
                return Task.FromResult(ReleaseShmResponse);
            }

            private static DetectResponse DefaultDetectResponse()
            {
                var proto = new DetectionResultProto
                {
                    Task = "det",
                    Score = 0.95,
                };
                proto.Scores.Add(0.95);
                proto.Labels.Add("defect");
                proto.BoxesFlat.AddRange(new[] { 10.0, 20.0, 30.0, 40.0 });
                proto.BoxCount = 1;
                proto.Extra.Add("source", "fake");
                return new DetectResponse { Success = true, Result = proto };
            }
        }
    }
}
