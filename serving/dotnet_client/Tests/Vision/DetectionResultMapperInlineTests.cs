using System;
using VisionAgent.Shared.Protos.AutoVisionAgent;
using VisionAgent.Shared.Services.Vision;
using Xunit;

namespace VisionAgent.Shared.Tests.Vision
{
    /// <summary>
    /// W17（v3 P1-1）：小数组内联通道。夹具字节与 Python 侧实编对齐——
    /// bool_rle 夹具来自 serving.mask_codec.encode_mask_rle 实测输出、
    /// float32 夹具来自 struct.pack("&lt;4f", ...) 实测输出（跨语言一致性锚）。
    /// </summary>
    public class DetectionResultMapperInlineTests
    {
        private static SharedMemoryHandle Meta(string dtype, params int[] shape)
        {
            var handle = new SharedMemoryHandle { Dtype = dtype };
            handle.Shape.Add(shape);
            return handle;
        }

        private static byte[] Int32Le(params int[] values)
        {
            var bytes = new byte[values.Length * 4];
            Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
            return bytes;
        }

        // Python 实测：encode_mask_rle([[[True, False], [False, True]]])
        //   → runs = [0, 1, 2, 1]（False 起始交替游程）
        private static readonly byte[] RleFixture = new byte[]
        {
            0x00, 0x00, 0x00, 0x00,
            0x01, 0x00, 0x00, 0x00,
            0x02, 0x00, 0x00, 0x00,
            0x01, 0x00, 0x00, 0x00,
        };

        // Python 实测：struct.pack("<4f", 1f, 2.5f, -3f, 4f)
        private static readonly byte[] Float32Fixture = new byte[]
        {
            0x00, 0x00, 0x80, 0x3f,
            0x00, 0x00, 0x20, 0x40,
            0x00, 0x00, 0x40, 0xc0,
            0x00, 0x00, 0x80, 0x40,
        };

        [Fact]
        public void DecodeMasks_BoolRle_MatchesPythonEncoderFixture()
        {
            var mask = SharedMemoryReader.DecodeMasks(RleFixture, Meta("bool_rle", 1, 2, 2));
            Assert.True(mask[0, 0, 0]);
            Assert.False(mask[0, 0, 1]);
            Assert.False(mask[0, 1, 0]);
            Assert.True(mask[0, 1, 1]);
        }

        [Fact]
        public void DecodeMasks_RawBool_BytesToBool()
        {
            var mask = SharedMemoryReader.DecodeMasks(
                new byte[] { 1, 0, 0, 0 }, Meta("bool", 1, 2, 2));
            Assert.True(mask[0, 0, 0]);
            Assert.False(mask[0, 0, 1]);
            Assert.False(mask[0, 1, 0]);
            Assert.False(mask[0, 1, 1]);
        }

        [Fact]
        public void DecodeKeypoints_Float32LittleEndian_PromotesToDouble()
        {
            var kps = SharedMemoryReader.DecodeKeypoints(Float32Fixture, Meta("float32", 1, 2, 2));
            Assert.Equal(1.0, kps[0, 0, 0], 5);
            Assert.Equal(2.5, kps[0, 0, 1], 5);
            Assert.Equal(-3.0, kps[0, 1, 0], 5);
            Assert.Equal(4.0, kps[0, 1, 1], 5);
        }

        [Fact]
        public void Mapper_PrefersInlineMasks_WithoutShmRead()
        {
            // 句柄 length=0（无 shm 区域）：若 Mapper 误走 shm 路径，Masks 将为
            // null——断言非空且解码正确即证明内联优先路径生效。
            var proto = new DetectionResultProto
            {
                Task = "pseg",
                MasksInline = Google.Protobuf.ByteString.CopyFrom(RleFixture),
                MasksShm = Meta("bool_rle", 1, 2, 2),
            };

            var result = DetectionResultMapper.ToDetectionResult(proto, new SharedMemoryReader());

            Assert.NotNull(result.Masks);
            Assert.Single(result.Masks!);
            Assert.True(result.Masks![0][0, 0]);
            Assert.False(result.Masks![0][0, 1]);
            Assert.False(result.Masks![0][1, 0]);
            Assert.True(result.Masks![0][1, 1]);
        }

        [Fact]
        public void Mapper_PrefersInlineKeypoints_WithoutShmRead()
        {
            var proto = new DetectionResultProto
            {
                Task = "pose",
                KeypointsInline = Google.Protobuf.ByteString.CopyFrom(Float32Fixture),
                KeypointsShm = Meta("float32", 1, 2, 2),
            };

            var result = DetectionResultMapper.ToDetectionResult(proto, new SharedMemoryReader());

            Assert.NotNull(result.Keypoints);
            Assert.Single(result.Keypoints!);
            Assert.Equal(1.0, result.Keypoints![0][0, 0], 5);
            Assert.Equal(2.5, result.Keypoints![0][0, 1], 5);
            Assert.Equal(-3.0, result.Keypoints![0][1, 0], 5);
            Assert.Equal(4.0, result.Keypoints![0][1, 1], 5);
        }
    }
}
