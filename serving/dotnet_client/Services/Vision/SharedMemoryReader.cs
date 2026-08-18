using System;
using System.Collections.Generic;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Linq;
using VisionAgent.Shared.Protos.AutoVisionAgent;

namespace VisionAgent.Shared.Services.Vision
{
    /// <summary>
    /// 共享内存读取器：按 <see cref="SharedMemoryHandle"/> 从文件映射 MMF
    /// 读取大块二进制数据（大图、分割掩码、关键点），与 AutoVisionAgent
    /// serving 端 <c>serving.shared_memory.SharedMemoryManager</c> 契约对齐。
    /// </summary>
    /// <remarks>
    /// 契约：生产方（Python serving 或本端写出）创建临时文件并写入原始字节，
    /// 句柄携带 <c>file_path / offset / length / dtype / shape</c>。
    /// 本读取器按 dtype 解释字节并按 shape 还原为多维数组。
    /// 支持的 dtype：uint8 / float32 / float64 / bool。
    /// </remarks>
    public sealed class SharedMemoryReader : IDisposable
    {
        /// <summary>读取句柄指定区间为原始字节。</summary>
        public byte[] ReadBytes(SharedMemoryHandle handle)
        {
            if (handle is null) throw new ArgumentNullException(nameof(handle));
            if (handle.Length <= 0) return Array.Empty<byte>();

            using var mmf = MemoryMappedFile.CreateFromFile(
                handle.FilePath, FileMode.Open, mapName: null, 0, MemoryMappedFileAccess.Read);
            using var accessor = mmf.CreateViewAccessor(handle.Offset, handle.Length, MemoryMappedFileAccess.Read);
            var buffer = new byte[handle.Length];
            accessor.ReadArray(0, buffer, 0, buffer.Length);
            return buffer;
        }

        /// <summary>按句柄 dtype/shape 还原为 uint8 数组。dtype 必须为 uint8。</summary>
        public byte[] ReadUInt8(SharedMemoryHandle handle)
        {
            if (!string.Equals(handle.Dtype, "uint8", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException($"dtype 不匹配：期望 uint8，实际 {handle.Dtype}");
            return ReadBytes(handle);
        }

        /// <summary>
        /// 读取 (N,H,W) bool 掩码为三维数组 [N,H,W]。
        /// 用于 <see cref="DetectionResultProto.MasksShm"/>。
        /// </summary>
        public bool[,,] ReadMasks(SharedMemoryHandle handle)
        {
            if (handle is null || handle.Length <= 0) return EmptyBool3D();
            return DecodeMasks(ReadBytes(handle), handle);
        }

        /// <summary>
        /// 从载荷字节解码 (N,H,W) bool 掩码（W17：共享内存与 proto 内联两路共用）。
        /// <paramref name="meta"/> 携带 dtype/shape；dtype 支持：
        /// <list type="bullet">
        /// <item><c>bool</c>：原始字节（每元素 1 字节）。</item>
        /// <item><c>bool_rle</c>（W7）：int32 小端交替游程、False 起始、C 序展平，
        /// 与 Python <c>serving.mask_codec</c> 契约一致（大掩码压缩传输）。</item>
        /// </list>
        /// </summary>
        public static bool[,,] DecodeMasks(byte[] raw, SharedMemoryHandle meta)
        {
            if (raw is null) throw new ArgumentNullException(nameof(raw));
            if (meta is null) throw new ArgumentNullException(nameof(meta));

            var isRaw = string.Equals(meta.Dtype, "bool", StringComparison.OrdinalIgnoreCase);
            var isRle = string.Equals(meta.Dtype, "bool_rle", StringComparison.OrdinalIgnoreCase);
            if (!isRaw && !isRle)
                throw new InvalidOperationException($"掩码 dtype 不匹配：期望 bool/bool_rle，实际 {meta.Dtype}");

            var shape = meta.Shape;
            int n = shape.Count > 0 ? shape[0] : 0;
            int h = shape.Count > 1 ? shape[1] : 0;
            int w = shape.Count > 2 ? shape[2] : 0;
            long total = (long)n * h * w;

            if (isRaw)
            {
                if (total != raw.Length)
                    throw new InvalidOperationException(
                        $"掩码形状 [{n},{h},{w}] 与数据长度 {raw.Length} 不一致。");

                var masks = new bool[n, h, w];
                int idx = 0;
                for (int i = 0; i < n; i++)
                    for (int j = 0; j < h; j++)
                        for (int k = 0; k < w; k++)
                            masks[i, j, k] = raw[idx++] != 0;
                return masks;
            }

            // bool_rle：游程解码
            if (raw.Length == 0 || raw.Length % 4 != 0)
                throw new InvalidOperationException(
                    $"bool_rle 载荷长度 {raw.Length} 非 4 字节对齐，无法解码。");
            var runs = new int[raw.Length / 4];
            Buffer.BlockCopy(raw, 0, runs, 0, raw.Length);

            long sum = 0;
            foreach (var r in runs)
            {
                if (r < 0)
                    throw new InvalidOperationException("bool_rle 游程包含负值，载荷损坏。");
                sum += r;
            }
            if (sum != total)
                throw new InvalidOperationException(
                    $"bool_rle 游程之和 {sum} 与形状 [{n},{h},{w}] 元素数 {total} 不一致。");

            var decoded = new bool[n, h, w];
            int flat = 0;
            bool value = false;
            int hw = h * w;
            foreach (var run in runs)
            {
                for (int c = 0; c < run; c++)
                {
                    decoded[flat / hw, (flat % hw) / w, flat % w] = value;
                    flat++;
                }
                value = !value;
            }
            return decoded;
        }

        /// <summary>
        /// 读取 (N,K,D) 关键点为三维 double 数组 [N,K,D]。
        /// dtype 可为 float32 或 float64，统一提升为 double。
        /// 用于 <see cref="DetectionResultProto.KeypointsShm"/>。
        /// </summary>
        public double[,,] ReadKeypoints(SharedMemoryHandle handle)
        {
            if (handle is null || handle.Length <= 0) return EmptyDouble3D();
            return DecodeKeypoints(ReadBytes(handle), handle);
        }

        /// <summary>
        /// 从载荷字节解码 (N,K,D) 关键点（W17：共享内存与 proto 内联两路共用）。
        /// <paramref name="meta"/> 携带 dtype/shape；float32/float64 统一提升为 double。
        /// </summary>
        public static double[,,] DecodeKeypoints(byte[] raw, SharedMemoryHandle meta)
        {
            if (raw is null) throw new ArgumentNullException(nameof(raw));
            if (meta is null) throw new ArgumentNullException(nameof(meta));

            var shape = meta.Shape;
            int n = shape.Count > 0 ? shape[0] : 0;
            int k = shape.Count > 1 ? shape[1] : 0;
            int d = shape.Count > 2 ? shape[2] : 0;

            var values = new double[n * k * d];
            if (string.Equals(meta.Dtype, "float32", StringComparison.OrdinalIgnoreCase))
            {
                if (raw.Length != values.Length * 4)
                    throw new InvalidOperationException("关键点数据长度与 float32 形状不匹配。");
                // float 中转后提升为 double，避免直接把 float 字节写进 double 数组
                var floats = new float[values.Length];
                Buffer.BlockCopy(raw, 0, floats, 0, raw.Length);
                for (int i = 0; i < floats.Length; i++) values[i] = floats[i];
            }
            else if (string.Equals(meta.Dtype, "float64", StringComparison.OrdinalIgnoreCase))
            {
                if (raw.Length != values.Length * 8)
                    throw new InvalidOperationException("关键点数据长度与 float64 形状不匹配。");
                Buffer.BlockCopy(raw, 0, values, 0, raw.Length);
            }
            else
            {
                throw new InvalidOperationException($"关键点 dtype 不支持：{meta.Dtype}");
            }

            var kps = new double[n, k, d];
            int idx = 0;
            for (int i = 0; i < n; i++)
                for (int j = 0; j < k; j++)
                    for (int t = 0; t < d; t++)
                        kps[i, j, t] = values[idx++];
            return kps;
        }

        /// <summary>读取共享内存图像（uint8，shape=[H,W,C]）为 HxWxC 字节数组。</summary>
        public byte[,,] ReadImage(SharedMemoryHandle handle)
        {
            if (handle is null || handle.Length <= 0)
                throw new ArgumentException("图像共享内存句柄为空。", nameof(handle));
            if (!string.Equals(handle.Dtype, "uint8", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException($"图像 dtype 不匹配：期望 uint8，实际 {handle.Dtype}");

            var raw = ReadBytes(handle);
            var shape = handle.Shape;
            int h = shape.Count > 0 ? shape[0] : 0;
            int w = shape.Count > 1 ? shape[1] : 0;
            int c = shape.Count > 2 ? shape[2] : 1;
            if (h * w * c != raw.Length)
                throw new InvalidOperationException(
                    $"图像形状 [{h},{w},{c}] 与数据长度 {raw.Length} 不一致。");

            var img = new byte[h, w, c];
            int idx = 0;
            for (int i = 0; i < h; i++)
                for (int j = 0; j < w; j++)
                    for (int t = 0; t < c; t++)
                        img[i, j, t] = raw[idx++];
            return img;
        }

        private static bool[,,] EmptyBool3D() => new bool[0, 0, 0];
        private static double[,,] EmptyDouble3D() => new double[0, 0, 0];

        public void Dispose() { /* 视图与 MMF 在各方法内 using 释放，此处无需持有状态 */ }
    }
}
