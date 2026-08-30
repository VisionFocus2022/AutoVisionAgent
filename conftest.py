"""pytest 全局配置（R3-15）。

注册自定义 marker，消除 PytestUnknownMarkWarning。

W23（v4 P2-1c）：测试态/生产态日志隔离接线——模块导入期（先于一切测试
收集与导入）把 AVA_LOG_DIR 指向会话级临时目录，使 gui.main.setup_logging /
serving.server._resolve_log_dir（./logs 相对解析）与 core.audit_logger /
core.detection_history（仓库绝对路径默认）四写入方全部重定向，隔离测试
噪音与生产可观测性文件（实证 autovision.log 51,647 行中 1,990 行
pytest-of 混写）。
"""
import os
import shutil
import tempfile

# setdefault 不覆盖显式注入（tests/test_w23_log_isolation.py 的定向用例
# 在测试内 setenv 仍生效）；生产/打包 exe 不设该 env，行为不变。
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="ava-test-logs-")
os.environ.setdefault("AVA_LOG_DIR", _TEST_LOG_DIR)


def pytest_configure(config):
    """注册自定义 marker。"""
    config.addinivalue_line(
        "markers", "unit: 单元测试（快速、无外部依赖）"
    )
    config.addinivalue_line(
        "markers", "e2e: 端到端测试（可能需要 GPU / 模型权重）"
    )


def pytest_sessionfinish(session, exitstatus) -> None:
    """会话结束清理临时日志目录。

    先关闭指向会话目录的 root FileHandler——Windows 下句柄不释放时
    rmtree 必败（对抗验证员实证：每 pytest 会话泄漏一个 %TEMP% 目录
    无上限累积）；atexit flush 可能在清理后重建空目录，同为 %TEMP%
    孤儿，无害且不影响仓库 logs/ 冻结。
    """
    import logging

    for h in list(logging.getLogger().handlers):
        base = getattr(h, "baseFilename", "")
        if base and base.startswith(_TEST_LOG_DIR):
            h.close()
            logging.getLogger().removeHandler(h)
    shutil.rmtree(_TEST_LOG_DIR, ignore_errors=True)
