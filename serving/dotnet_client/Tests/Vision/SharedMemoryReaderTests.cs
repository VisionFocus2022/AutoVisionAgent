using System;
using System.IO;
using System.Linq;
using VisionAgent.Shared.Protos.AutoVisionAgent;
using VisionAgent.Shared.Services.Vision;
using Xunit;

namespace VisionAgent.Shared.Tests.Vision
{
    /// <summary>
    /// <see cref="SharedMemoryReader"/> 单元测试：验证按句柄从文件映射 MMF
    /// 读回各 dtype/shape 数组的字节序与形状契约，与 Python serving 端
    /// <c>SharedMemoryManager</c> 对齐。
    /// </summary>
    public sealed class SharedMemoryReaderTests : IDisposable
    {
        private readonly SharedMemoryReader _reader = new();
        private readonly System.Collections.Generic.List<string> _tempFiles = new();

        public void Dispose()
        {
            foreach (var path in _tempFiles)
            {
                try { File.Delete(path); } catch { /* 忽略 */ }
            }
        }

        /// <summary>写出临时文件并构造句柄（offset=0，shape 由参数给定）。</summary>
        private SharedMemoryHandle WriteTemp(byte[] data, string dtype, params int[] shape)
        {
            var path = Path.Combine(Path.GetTempPath(), $"ava_test_{Guid.NewGuid():N}.bin");
            File.WriteAllBytes(path, data);
            _tempFiles.Add(path);
            var handle = new SharedMemoryHandle
            {
                FilePath = path,
                Offset = 0,
                Length = data.Length,
                Dtype = dtype,
            };
            handle.Shape.AddRange(shape);
            return handle;
        }

        // ------------------------------- uint8 / 图像 ------------------------------- //

        [Fact]
        public void ReadUInt8_RoundTrips_PlainBytes()
        {
            var data = new byte[] { 1, 2, 3, 255, 0 };
            var handle = WriteTemp(data, "uint8", data.Length);

            var read = _reader.ReadUInt8(handle);

            Assert.Equal(data, read);
        }

        [Fact]
        public void ReadImage_RoundTrips_3Channel()
        {
            // 2×2×3 RGB 图像，行优先字节序（与 Python numpy C-order 对齐）
            var img = new byte[,,]
            {
                { { 1, 2, 3 }, { 4, 5, 6 } },
                { { 7, 8, 9 }, { 10, 11, 12 } },
            };
            var flat = img.Cast<byte>().ToArray();
            var handle = WriteTemp(flat, "uint8", 2, 2, 3);

            var read = _reader.ReadImage(handle);

            Assert.Equal(2, read.GetLength(0));
            Assert.Equal(2, read.GetLength(1));
            Assert.Equal(3, read.GetLength(2));
            Assert.Equal(flat, read.Cast<byte>().ToArray());
        }

        [Fact]
        public void ReadImage_Throws_OnDtypeMismatch()
        {
            var handle = WriteTemp(new byte[] { 1, 2 }, "bool", 1, 1, 2);
            Assert.Throws<InvalidOperationException>(() => _reader.ReadImage(handle));
        }

        [Fact]
        public void ReadImage_Throws_OnShapeLengthMismatch()
        {
            var handle = WriteTemp(new byte[] { 1, 2, 3 }, "uint8", 2, 2, 2); // 声明 8 字节，实际 3
            Assert.Throws<InvalidOperationException>(() => _reader.ReadImage(handle));
        }

        // ----------------------------------- bool 掩码 ---------------------------------- //

        [Fact]
        public void ReadMasks_RoundTrips_Bool3D()
        {
            // shape [1,2,2]，非零即 true
            var data = new byte[] { 1, 0, 5, 0 };
            var handle = WriteTemp(data, "bool", 1, 2, 2);

            var masks = _reader.ReadMasks(handle);

            Assert.Equal(1, masks.GetLength(0));
            Assert.True(masks[0, 0, 0]);
            Assert.False(masks[0, 0, 1]);
            Assert.True(masks[0, 1, 0]);
            Assert.False(masks[0, 1, 1]);
        }

        [Fact]
        public void ReadMasks_Throws_OnDtypeMismatch()
        {
            var handle = WriteTemp(new byte[] { 1, 0 }, "uint8", 1, 1, 2);
            Assert.Throws<InvalidOperationException>(() => _reader.ReadMasks(handle));
        }

        [Fact]
        public void ReadMasks_EmptyHandle_ReturnsEmpty3D()
        {
            var handle = new SharedMemoryHandle { FilePath = string.Empty, Length = 0, Dtype = "bool" };
            var masks = _reader.ReadMasks(handle);
            Assert.Equal(0, masks.GetLength(0));
        }

        // ----------------------------------- 关键点 ---------------------------------- //

        [Fact]
        public void ReadKeypoints_RoundTrips_Float32()
        {
            // shape [1,2,2] = 4 个 float32 = 16 字节
            var values = new float[] { 1.5f, 2.5f, 3.5f, 4.5f };
            var bytes = new byte[values.Length * 4];
            Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
            var handle = WriteTemp(bytes, "float32", 1, 2, 2);

            var kps = _reader.ReadKeypoints(handle);

            Assert.Equal(1, kps.GetLength(0));
            Assert.Equal(2, kps.GetLength(1));
            Assert.Equal(2, kps.GetLength(2));
            Assert.Equal(1.5, kps[0, 0, 0], 5);
            Assert.Equal(2.5, kps[0, 0, 1], 5);
            Assert.Equal(3.5, kps[0, 1, 0], 5);
            Assert.Equal(4.5, kps[0, 1, 1], 5);
        }

        [Fact]
        public void ReadKeypoints_RoundTrips_Float64()
        {
            var values = new double[] { 10.25, 20.75 };
            var bytes = new byte[values.Length * 8];
            Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
            var handle = WriteTemp(bytes, "float64", 1, 2, 1);

            var kps = _reader.ReadKeypoints(handle);

            Assert.Equal(10.25, kps[0, 0, 0], 9);
            Assert.Equal(20.75, kps[0, 1, 0], 9);
        }

        [Fact]
        public void ReadKeypoints_Throws_OnUnsupportedDtype()
        {
            var handle = WriteTemp(new byte[] { 0, 0, 0, 0 }, "int32", 1, 1, 1);
            Assert.Throws<InvalidOperationException>(() => _reader.ReadKeypoints(handle));
        }

        [Fact]
        public void ReadKeypoints_Throws_OnLengthMismatch()
        {
            // 声明 float32（4 字节/元素）但只给 3 字节
            var handle = WriteTemp(new byte[] { 1, 2, 3 }, "float32", 1, 1, 1);
            Assert.Throws<InvalidOperationException>(() => _reader.ReadKeypoints(handle));
        }

        // ----------------------------------- 原始字节 --------------------------------- //

        [Fact]
        public void ReadBytes_Returns_RawSpan()
        {
            var data = new byte[] { 10, 20, 30, 40, 50 };
            var handle = WriteTemp(data, "uint8", data.Length);

            var read = _reader.ReadBytes(handle);

            Assert.Equal(data, read);
        }

        [Fact]
        public void ReadBytes_EmptyHandle_ReturnsEmpty()
        {
            var handle = new SharedMemoryHandle { FilePath = string.Empty, Length = 0, Dtype = "uint8" };
            Assert.Empty(_reader.ReadBytes(handle));
        }

        // ------------------------------- bool_rle（W7：与 Python mask_codec 契约对齐） ------------------------------- //

        /// <summary>int32 LE 交替游程（False 起始）→ [N,H,W] bool。</summary>
        private static byte[] RunsToBytes(params int[] runs)
        {
            var bytes = new byte[runs.Length * 4];
            System.Buffer.BlockCopy(runs, 0, bytes, 0, bytes.Length);
            return bytes;
        }

        [Fact]
        public void ReadMasks_Decodes_BoolRle_RunContract()
        {
            // Python: encode([[0,0,1,1,1,0]]) → runs [2,3,1]
            var handle = WriteTemp(RunsToBytes(2, 3, 1), "bool_rle", 1, 1, 6);

            var masks = _reader.ReadMasks(handle);

            Assert.Equal(1, masks.GetLength(0));
            Assert.False(masks[0, 0, 0]);
            Assert.False(masks[0, 0, 1]);
            Assert.True(masks[0, 0, 2]);
            Assert.True(masks[0, 0, 3]);
            Assert.True(masks[0, 0, 4]);
            Assert.False(masks[0, 0, 5]);
        }

        [Fact]
        public void ReadMasks_BoolRle_HandlesZeroLeadingRun_AndMultiInstance()
        {
            // 首像素为 True：False 首段长度 0（runs [0,3,2]）；
            // 两实例各 1×5：inst0=[1,1,1,0,0], inst1=[0,0,1,1,0]
            var handle = WriteTemp(RunsToBytes(0, 3, 4, 2, 1), "bool_rle", 2, 1, 5);

            var masks = _reader.ReadMasks(handle);

            Assert.True(masks[0, 0, 0] && masks[0, 0, 1] && masks[0, 0, 2]);
            Assert.False(masks[0, 0, 3] || masks[0, 0, 4]);
            Assert.False(masks[1, 0, 0] || masks[1, 0, 1]);
            Assert.True(masks[1, 0, 2] && masks[1, 0, 3]);
            Assert.False(masks[1, 0, 4]);
        }

        [Fact]
        public void ReadMasks_BoolRle_Throws_OnRunSumMismatch()
        {
            var handle = WriteTemp(RunsToBytes(4), "bool_rle", 1, 2, 3); // 4 != 6

            Assert.Throws<InvalidOperationException>(() => _reader.ReadMasks(handle));
        }

        [Fact]
        public void ReadMasks_BoolRle_Throws_OnNegativeRun()
        {
            var handle = WriteTemp(RunsToBytes(-1, 7), "bool_rle", 1, 1, 6);

            Assert.Throws<InvalidOperationException>(() => _reader.ReadMasks(handle));
        }

        [Fact]
        public void ReadMasks_BoolRle_Throws_OnTruncatedRunBytes()
        {
            var handle = WriteTemp(new byte[] { 1, 2, 3 }, "bool_rle", 1, 1, 6); // 非 4 倍长

            Assert.Throws<InvalidOperationException>(() => _reader.ReadMasks(handle));
        }
    }
}
