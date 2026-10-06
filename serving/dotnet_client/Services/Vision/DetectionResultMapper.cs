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

            // W17（v3 P1-1）：小数组内联优先——inline 字段非空时，以同名 shm
            // 句柄携带的 dtype/shape 为元数据解码内联字节（句柄 file_path 空、
            // length 0，不触碰共享内存文件、无需回收）；否则大数组按句柄走
            // 共享内存读取（既有路径不变）。
            if (!proto.MasksInline.IsEmpty
                && proto.MasksShm is not null
                && !string.IsNullOrEmpty(proto.MasksShm.Dtype))
            {
                result.Masks = SplitMasks(SharedMemoryReader.DecodeMasks(
                    proto.MasksInline.ToByteArray(), proto.MasksShm));
            }
            else if (shmReader is not null && proto.MasksShm is not null && proto.MasksShm.Length > 0)
            {
                result.Masks = SplitMasks(shmReader.ReadMasks(proto.MasksShm));
            }

            if (!proto.KeypointsInline.IsEmpty
                && proto.KeypointsShm is not null
                && !string.IsNullOrEmpty(proto.KeypointsShm.Dtype))
            {
                result.Keypoints = SplitKeypoints(SharedMemoryReader.DecodeKeypoints(
                    proto.KeypointsInline.ToByteArray(), proto.KeypointsShm));
            }
            else if (shmReader is not null && proto.KeypointsShm is not null && proto.KeypointsShm.Length > 0)
            {
                result.Keypoints = SplitKeypoints(shmReader.ReadKeypoints(proto.KeypointsShm));
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
        /// <remarks>
        /// ADR-0006（2026-10-06 枚举对账）：与 Python TaskType 值域对齐——
        /// 移除 Python 侧不存在的 "vlm"（错误路由源），补 sseg/sgan/super。
        /// 未知值此前静默回退 Det（fail-open：错误任务名被吞成目标检测），
        /// 现抛 ArgumentException 显式拒绝（fail-closed，与服务端同语义）。
        /// </remarks>
        public static DetectionTaskType MapTaskType(string task)
        {
            var name = (task ?? string.Empty).ToLowerInvariant();
            return name switch
            {
                "cls" => DetectionTaskType.Cls,
                "det" => DetectionTaskType.Det,
                "seg" => DetectionTaskType.Seg,
                "pseg" => DetectionTaskType.Seg,   // YOLOv8-seg 归入实例分割
                "pose" => DetectionTaskType.Pose,
                "sseg" => DetectionTaskType.Seg,   // 语义分割归入 Seg 展示
                "sgan" => DetectionTaskType.Det,   // 缺陷生成检测归入 Det 展示
                "super" => DetectionTaskType.Det,  // 超分增强检测归入 Det 展示
                "abdet" => DetectionTaskType.Abnormality,
                _ => throw new ArgumentException(
                    $"未知任务类型: {task ?? "(null)"}（与 Python TaskType 值域对账失败）",
                    nameof(task)),
            };
        }
    }
}
