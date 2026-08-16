using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using VisionAgent.Shared.Enums.Vision;
using VisionAgent.Shared.Models.Vision;
using VisionAgent.Shared.Protos.AutoVisionAgent;

namespace VisionAgent.Shared.Services.Vision
{
    /// <summary>
    /// 将 gRPC <see cref="DetectionResultProto"/>（含共享内存大块数据）
    /// 映射为统一的 <see cref="DetectionResult"/> POCO。
    /// </summary>
    public static class DetectionResultMapper
    {
        /// <summary>
        /// 把 proto 结果转换为 <see cref="DetectionResult"/>。
        /// masks/keypoints 若挂在共享内存上，由 <paramref name="shmReader"/> 读回。
        /// </summary>
        public static DetectionResult ToDetectionResult(
            DetectionResultProto proto,
            SharedMemoryReader shmReader)
        {
            if (proto is null) throw new ArgumentNullException(nameof(proto));

            var result = new DetectionResult
            {
                TaskType = MapTaskType(proto.Task),
                Score = proto.Score,
                Scores = proto.Scores.ToList(),
                Labels = proto.Labels.ToList(),
                Boxes = BuildBoxes(proto),
                Extra = proto.Extra.ToDictionary(p => p.Key, p => (object)p.Value),
            };

            if (shmReader is not null)
            {
                if (proto.MasksShm is not null && proto.MasksShm.Length > 0)
                {
                    result.Masks = SplitMasks(shmReader.ReadMasks(proto.MasksShm));
                }
                if (proto.KeypointsShm is not null && proto.KeypointsShm.Length > 0)
                {
                    result.Keypoints = SplitKeypoints(shmReader.ReadKeypoints(proto.KeypointsShm));
                }
            }

            return result;
        }

        /// <summary>proto 扁平 boxes_flat → N×4 二维数组。</summary>
        private static double[,]? BuildBoxes(DetectionResultProto proto)
        {
            int count = proto.BoxCount > 0 ? proto.BoxCount : proto.BoxesFlat.Count / 4;
            if (count <= 0) return null;

            var boxes = new double[count, 4];
            for (int i = 0; i < count; i++)
            {
                int baseIdx = i * 4;
                if (baseIdx + 3 >= proto.BoxesFlat.Count) break;
                boxes[i, 0] = proto.BoxesFlat[baseIdx];
                boxes[i, 1] = proto.BoxesFlat[baseIdx + 1];
                boxes[i, 2] = proto.BoxesFlat[baseIdx + 2];
                boxes[i, 3] = proto.BoxesFlat[baseIdx + 3];
            }
            return boxes;
        }

        /// <summary>(N,H,W) bool → N 个 H×W bool[,]（与现有 DetectionResult.Masks 契约一致）。</summary>
        private static List<bool[,]>? SplitMasks(bool[,,] masks)
        {
            int n = masks.GetLength(0);
            if (n == 0) return null;
            int h = masks.GetLength(1);
            int w = masks.GetLength(2);
            var list = new List<bool[,]>(n);
            for (int i = 0; i < n; i++)
            {
                var slice = new bool[h, w];
                for (int y = 0; y < h; y++)
                    for (int x = 0; x < w; x++)
                        slice[y, x] = masks[i, y, x];
                list.Add(slice);
            }
            return list;
        }

        /// <summary>(N,K,D) double → N 个 K×D double[,]。</summary>
        private static List<double[,]>? SplitKeypoints(double[,,] kps)
        {
            int n = kps.GetLength(0);
            if (n == 0) return null;
            int k = kps.GetLength(1);
            int d = kps.GetLength(2);
            var list = new List<double[,]>(n);
            for (int i = 0; i < n; i++)
            {
                var slice = new double[k, d];
                for (int a = 0; a < k; a++)
                    for (int b = 0; b < d; b++)
                        slice[a, b] = kps[i, a, b];
                list.Add(slice);
            }
            return list;
        }

        /// <summary>Python TaskType 字符串 → C# <see cref="DetectionTaskType"/>。</summary>
        public static DetectionTaskType MapTaskType(string task)
        {
            return (task ?? string.Empty).ToLowerInvariant() switch
            {
                "cls" => DetectionTaskType.Cls,
                "det" => DetectionTaskType.Det,
                "seg" => DetectionTaskType.Seg,
                "pseg" => DetectionTaskType.Seg,   // YOLOv8-seg 归入实例分割
                "pose" => DetectionTaskType.Pose,
                "abdet" => DetectionTaskType.Abnormality,
                "vlm" => DetectionTaskType.Vlm,
                _ => DetectionTaskType.Det,
            };
        }
    }
}
