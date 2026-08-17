using System;
using System.IO;
using Grpc.Net.Client;
using NLog;
using NLog.Config;
using NLog.Targets;
using VisionAgent.Shared.Services.Vision;
using Xunit;

namespace VisionAgent.Shared.Tests.Vision
{
    /// <summary>
    /// W14 C6 P2-4：AutoVisionAgentClient 启动清扫陈旧 ava_*.bin 残留
    /// （与 Python serving 端 SharedMemoryManager._sweep_stale_files 同语义：
    /// 仅按「ava_ 前缀 + .bin 后缀 + mtime 年龄超阈值（2h）」判定，
    /// 其他文件一律不动；删除失败——如被他进程占用——跳过仅告警，
    /// 留给下次启动再扫）+ File.Delete 空 catch 接 NLog 告警。
    /// </summary>
    public sealed class AutoVisionAgentClientShmSweepTests : IDisposable
    {
        private readonly string _dir;

        public AutoVisionAgentClientShmSweepTests()
        {
            _dir = Path.Combine(
                Path.GetTempPath(), "ava_sweep_tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_dir);
        }

        public void Dispose()
        {
            try { Directory.Delete(_dir, recursive: true); }
            catch { /* 测试残留尽力清理，不阻断其他用例 */ }
        }

        private static string Touch(string dir, string name, DateTime? lastWriteUtc = null)
        {
            var path = Path.Combine(dir, name);
            File.WriteAllText(path, "x");
            if (lastWriteUtc is { } t)
                File.SetLastWriteTimeUtc(path, t);
            return path;
        }

        [Fact]
        public void Sweep_RemovesOnlyStaleAvaBinFiles()
        {
            var stale = Touch(_dir, "ava_stale.bin", DateTime.UtcNow.AddHours(-3));
            var fresh = Touch(_dir, "ava_fresh.bin");
            var other = Touch(_dir, "other_stale.bin", DateTime.UtcNow.AddHours(-3));

            int removed = AutoVisionAgentClient.SweepStaleShmFiles(
                _dir, TimeSpan.FromHours(2), static () => DateTime.UtcNow);

            Assert.Equal(1, removed);
            Assert.False(File.Exists(stale));   // 超龄 → 删除
            Assert.True(File.Exists(fresh));    // 未超龄 → 保留
            Assert.True(File.Exists(other));    // 非 ava_*.bin → 一律不动
        }

        [Fact]
        public void Sweep_TreatsAgeByInjectedClock()
        {
            // 文件本身新鲜，注入「3 小时后」的时钟 → 按陈旧删除（时间戳可注入）
            var file = Touch(_dir, "ava_clock.bin");

            int removed = AutoVisionAgentClient.SweepStaleShmFiles(
                _dir, TimeSpan.FromHours(2), () => DateTime.UtcNow.AddHours(3));

            Assert.Equal(1, removed);
            Assert.False(File.Exists(file));
        }

        [Fact]
        public void Sweep_LockedFile_SkipsAndWarnsViaNLog()
        {
            var locked = Touch(_dir, "ava_locked.bin", DateTime.UtcNow.AddHours(-3));
            // FileShare.None 独占：File.Delete 必失败 → 只能跳过 + 告警
            using var lease = new FileStream(
                locked, FileMode.Open, FileAccess.Read, FileShare.None);

            var memory = new MemoryTarget
            {
                Layout = "${level}|${message}|${exception:format=message}",
            };
            var config = new LoggingConfiguration();
            config.AddRule(LogLevel.Warn, LogLevel.Fatal, memory);
            var oldConfig = LogManager.Configuration;
            LogManager.Configuration = config;
            try
            {
                int removed = AutoVisionAgentClient.SweepStaleShmFiles(
                    _dir, TimeSpan.FromHours(2), static () => DateTime.UtcNow);

                Assert.Equal(0, removed);                 // 跳过不中断
                Assert.True(File.Exists(locked));         // 文件留存下次再扫
                Assert.Contains(memory.Logs, m =>
                    m.Contains("ava_locked.bin") &&
                    m.Contains("清扫") &&
                    m.StartsWith("Warn", StringComparison.Ordinal));
            }
            finally
            {
                LogManager.Configuration = oldConfig;
            }
        }

        [Fact]
        public void Ctor_SweepsCustomShmDir_OnConstruction()
        {
            var stale = Touch(_dir, "ava_ctor_stale.bin", DateTime.UtcNow.AddHours(-3));

            // 通道惰性连接：构造期不发请求，无需真实服务端
            using var channel = GrpcChannel.ForAddress("http://127.0.0.1:1");
            using var client = new AutoVisionAgentClient(
                channel, shmReader: null, shmDir: _dir);

            Assert.False(File.Exists(stale)); // 启动（构造）即清扫
        }
    }
}
