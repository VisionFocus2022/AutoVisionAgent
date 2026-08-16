namespace VisionAgent.Shared.Enums.Vision
{
    /// <summary>
    /// 检测任务类型（与 Python 侧 <c>core.interfaces_supervised.TaskType</c>
    /// 字符串值对齐；pseg 归入 Seg、abdet 映射 Abnormality）。
    /// W7 修复：本目录随根共享库迁移时缺失，按 DetectionResultMapper 契约重建。
    /// </summary>
    public enum DetectionTaskType
    {
        /// <summary>分类。</summary>
        Cls,

        /// <summary>目标检测。</summary>
        Det,

        /// <summary>分割（语义/实例）。</summary>
        Seg,

        /// <summary>关键点/姿态。</summary>
        Pose,

        /// <summary>异常检测。</summary>
        Abnormality,

        /// <summary>视觉语言模型任务。</summary>
        Vlm,
    }
}
