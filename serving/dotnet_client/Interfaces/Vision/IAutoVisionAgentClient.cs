using System.Collections.Generic;
using VisionAgent.Shared.Models.Vision;
using VisionAgent.Shared.Protos.AutoVisionAgent;

namespace VisionAgent.Shared.Interfaces.Vision
{
    /// <summary>
    /// AutoVisionAgent（Python serving）对外客户端契约。
    /// 通过 gRPC 调用模型检测能力，大块二进制数据走共享内存零拷贝。
    /// 实现见 <see cref="Services.Vision.AutoVisionAgentClient"/>。
    /// </summary>
    public interface IAutoVisionAgentClient
    {
        /// <summary>健康检查。</summary>
        PongResponse Ping();

        /// <summary>列出全部任务能力。</summary>
        IReadOnlyList<TaskInfo> ListTasks();

        /// <summary>查询单个任务状态。</summary>
        TaskInfo GetTaskInfo(string task);

        /// <summary>加载有监督引擎权重。</summary>
        /// <returns>成功与否；失败时 error 描述原因。</returns>
        (bool Success, string Error) LoadModel(string task, string weightsPath, string device = "cuda");

        /// <summary>卸载引擎、释放显存。</summary>
        (bool Success, string Error) UnloadModel(string task);

        /// <summary>用内联字节图像（小图）执行检测。</summary>
        DetectionResult? Detect(
            string task,
            byte[] imageBytes,
            string mode = "auto",
            float threshold = 0.5f,
            IList<string>? labels = null,
            IList<string>? prompts = null);

        /// <summary>用同机文件路径执行检测。</summary>
        DetectionResult? DetectFromFile(
            string task,
            string imagePath,
            string mode = "auto",
            float threshold = 0.5f,
            IList<string>? labels = null,
            IList<string>? prompts = null);

        /// <summary>用共享内存大图（RAW uint8 [H,W,C]）执行检测。</summary>
        DetectionResult? DetectViaSharedMemory(
            string task,
            SharedMemoryHandle imageShm,
            string mode = "auto",
            float threshold = 0.5f,
            IList<string>? labels = null,
            IList<string>? prompts = null);

        /// <summary>
        /// 把大图写入共享内存文件，返回句柄，供 <see cref="DetectViaSharedMemory"/> 使用。
        /// 用于避免大图走 gRPC protobuf 序列化。
        /// </summary>
        SharedMemoryHandle WriteImageToSharedMemory(byte[,,] imageRgb);

        /// <summary>回收由本客户端创建的共享内存文件。</summary>
        (bool Success, string Error) ReleaseSharedMemory(string filePath);
    }
}
