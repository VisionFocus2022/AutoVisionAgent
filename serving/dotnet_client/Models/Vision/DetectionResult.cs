using System.Collections.Generic;
using VisionAgent.Shared.Enums.Vision;

namespace VisionAgent.Shared.Models.Vision
{
    /// <summary>
    /// 统一检测结果模型（gRPC/proto 无关的 POCO）。
    /// W7 修复：本模型随根共享库迁移时缺失，按 DetectionResultMapper 与
    /// IAutoVisionAgentClient 契约重建。
    /// </summary>
    public sealed record DetectionResult
    {
        /// <summary>任务类型。</summary>
        public DetectionTaskType TaskType { get; init; }

        /// <summary>整图级分数（0~1；无逐框分数时使用）。</summary>
        public double Score { get; init; }

        /// <summary>逐检测分数。</summary>
        public IReadOnlyList<double> Scores { get; init; } = new List<double>();

        /// <summary>逐检测标签。</summary>
        public IReadOnlyList<string> Labels { get; init; } = new List<string>();

        /// <summary>检测框 N×4 [x1,y1,x2,y2]。</summary>
        public double[,]? Boxes { get; init; }

        /// <summary>分割掩码：每实例一张 H×W bool 图（mapper 构造后回填）。</summary>
        public IReadOnlyList<bool[,]>? Masks { get; set; }

        /// <summary>关键点：每实例 K×D（mapper 构造后回填）。</summary>
        public IReadOnlyList<double[,]>? Keypoints { get; set; }

        /// <summary>附加数据（字符串键值）。</summary>
        public IReadOnlyDictionary<string, object> Extra { get; init; }
            = new Dictionary<string, object>();
    }
}
