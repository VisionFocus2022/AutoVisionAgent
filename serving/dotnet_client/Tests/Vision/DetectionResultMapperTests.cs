using System;
using System.IO;
using System.Linq;
using VisionAgent.Shared.Enums.Vision;
using VisionAgent.Shared.Protos.AutoVisionAgent;
using VisionAgent.Shared.Services.Vision;
using Xunit;

namespace VisionAgent.Shared.Tests.Vision
{
    /// <summary>
    /// <see cref="DetectionResultMapper"/> 单元测试：验证 proto 结果（含共享内存大块数据）
    /// 到 <see cref="Models.Vision.DetectionResult"/> POCO 的映射契约。
    /// </summary>
    public sealed class DetectionResultMapperTests : IDisposable
    {
        private readonly SharedMemoryReader _reader = new();
        private readonly System.Collections.Generic.List<string> _tempFiles = new();

        public void Dispose()
        {
            foreach (var p in _tempFiles)
            {
                try { File.Delete(p); } catch { /* 忽略 */ }
            }
        }

        private SharedMemoryHandle WriteTemp(byte[] data, string dtype, params int[] shape)
        {
            var path = Path.Combine(Path.GetTempPath(), $"ava_map_{Guid.NewGuid():N}.bin");
            File.WriteAllBytes(path, data);
            _tempFiles.Add(path);
            var handle = new SharedMemoryHandle
            {
                FilePath = path, Offset = 0, Length = data.Length, Dtype = dtype,
            };
            handle.Shape.AddRange(shape);
            return handle;
        }

        // ----------------------------------- 标量 / boxes ------------------------------ //

        [Fact]
        public void ToDetectionResult_Maps_ScalarFields_And_Boxes()
        {
            var proto = new DetectionResultProto
            {
                Task = "det",
                Score = 0.87,
            };
            proto.Scores.AddRange(new[] { 0.9, 0.8 });
            proto.Labels.AddRange(new[] { "defect1", "defect2" });
            proto.BoxesFlat.AddRange(new[] { 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0 });
            proto.BoxCount = 2;
            proto.Extra.Add("source", "fake");

            var result = DetectionResultMapper.ToDetectionResult(proto, _reader);

            Assert.Equal(DetectionTaskType.Det, result.TaskType);
            Assert.Equal(0.87, result.Score);
            Assert.Equal(new[] { 0.9, 0.8 }, result.Scores.ToArray());
            Assert.Equal(new[] { "defect1", "defect2" }, result.Labels.ToArray());
            Assert.NotNull(result.Boxes);
            Assert.Equal(2, result.Boxes!.GetLength(0));
            Assert.Equal(4, result.Boxes.GetLength(1));
            Assert.Equal(10.0, result.Boxes[0, 0]);
            Assert.Equal(40.0, result.Boxes[0, 3]);
            Assert.Equal(50.0, result.Boxes[1, 0]);
            Assert.Equal(80.0, result.Boxes[1, 3]);
            Assert.Equal("fake", result.Extra["source"]);
        }

        [Fact]
        public void ToDetectionResult_BoxCount_InferredFromFlat_WhenZero()
        {
            // BoxCount=0 时应按 boxes_flat.Count/4 推断
            var proto = new DetectionResultProto { Task = "det" };
            proto.BoxesFlat.AddRange(new[] { 1.0, 2.0, 3.0, 4.0 });

            var result = DetectionResultMapper.ToDetectionResult(proto, _reader);

            Assert.NotNull(result.Boxes);
            Assert.Equal(1, result.Boxes!.GetLength(0));
            Assert.Equal(4, result.Boxes.GetLength(1));
        }

        [Fact]
        public void ToDetectionResult_NoBoxes_ReturnsNullBoxes()
        {
            var proto = new DetectionResultProto { Task = "cls" };

            var result = DetectionResultMapper.ToDetectionResult(proto, _reader);

            Assert.Null(result.Boxes);
            Assert.Null(result.Masks);
            Assert.Null(result.Keypoints);
        }

        // ----------------------------------- masks via shm ----------------------------- //

        [Fact]
        public void ToDetectionResult_Maps_Masks_ViaSharedMemory()
        {
            // 2 个 2×2 掩码 = 8 字节
            var data = new byte[] { 1, 0, 0, 1, 0, 1, 1, 0 };
            var handle = WriteTemp(data, "bool", 2, 2, 2);

            var proto = new DetectionResultProto { Task = "seg" };
            proto.MasksShm = handle;

            var result = DetectionResultMapper.ToDetectionResult(proto, _reader);

            Assert.NotNull(result.Masks);
            Assert.Equal(2, result.Masks!.Count);
            Assert.True(result.Masks[0][0, 0]);
            Assert.False(result.Masks[0][0, 1]);
            Assert.False(result.Masks[1][0, 0]);
            Assert.True(result.Masks[1][1, 0]);
        }

        // --------------------------------- keypoints via shm --------------------------- //

        [Fact]
        public void ToDetectionResult_Maps_Keypoints_ViaSharedMemory()
        {
            // shape [1,2,2] float32 = 4 floats = 16 字节
            var values = new float[] { 1.5f, 2.5f, 3.5f, 4.5f };
            var bytes = new byte[values.Length * 4];
            Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
            var handle = WriteTemp(bytes, "float32", 1, 2, 2);

            var proto = new DetectionResultProto { Task = "pose" };
            proto.KeypointsShm = handle;

            var result = DetectionResultMapper.ToDetectionResult(proto, _reader);

            Assert.NotNull(result.Keypoints);
            Assert.Single(result.Keypoints!);
            Assert.Equal(2, result.Keypoints[0].GetLength(0));
            Assert.Equal(2, result.Keypoints[0].GetLength(1));
            Assert.Equal(1.5, result.Keypoints[0][0, 0], 5);
            Assert.Equal(4.5, result.Keypoints[0][1, 1], 5);
        }

        [Fact]
        public void ToDetectionResult_NullReader_SkipsShmFields()
        {
            // reader=null 时不读 masks/keypoints，但标量字段仍映射
            var proto = new DetectionResultProto { Task = "det", Score = 0.5 };
            proto.MasksShm = new SharedMemoryHandle { FilePath = "x", Length = 1, Dtype = "bool" };

            var result = DetectionResultMapper.ToDetectionResult(proto, shmReader: null!);

            Assert.Equal(0.5, result.Score);
            Assert.Null(result.Masks);
        }

        // ------------------------------------ TaskType 映射 ---------------------------- //

        [Theory]
        [InlineData("cls", DetectionTaskType.Cls)]
        [InlineData("CLS", DetectionTaskType.Cls)]           // 大小写不敏感
        [InlineData("det", DetectionTaskType.Det)]
        [InlineData("seg", DetectionTaskType.Seg)]
        [InlineData("pseg", DetectionTaskType.Seg)]          // YOLOv8-seg 归入实例分割
        [InlineData("pose", DetectionTaskType.Pose)]
        [InlineData("abdet", DetectionTaskType.Abnormality)]
        [InlineData("unknown", DetectionTaskType.Det)]       // 未知回退 Det
        [InlineData("", DetectionTaskType.Det)]              // 空串回退 Det
        public void MapTaskType_Maps_KnownAndUnknown(string input, DetectionTaskType expected)
        {
            Assert.Equal(expected, DetectionResultMapper.MapTaskType(input));
        }
    }
}
