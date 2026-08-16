"""pytest 全局配置（R3-15）。

注册自定义 marker，消除 PytestUnknownMarkWarning。
"""
import pytest


def pytest_configure(config):
    """注册自定义 marker。"""
    config.addinivalue_line(
        "markers", "unit: 单元测试（快速、无外部依赖）"
    )
    config.addinivalue_line(
        "markers", "e2e: 端到端测试（可能需要 GPU / 模型权重）"
    )
