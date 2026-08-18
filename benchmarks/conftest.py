"""W19（v3 第三波 FR-1.1）：benchmarks/ 收集面声明。

根 pytest.ini 的 ``python_files = test_*.py`` 不匹配 ``bench_*.py``，目录扫描
（``pytest benchmarks``）默认不会收集基准文件；本钩子把 bench_*.py 显式声明
为可收集 Module。全量门禁不受影响：pytest.ini ``testpaths = tests``，只有
显式指定 ``benchmarks`` 路径时才进入收集面（AC-1.1"不入门禁分母"）。

运行口径（与 tests/uia 同法，见 pytest.ini 头注释）::

    .venv/Scripts/python.exe -m pytest benchmarks -o addopts= -q
"""
from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collect_file(file_path: Path, parent):
    """把 bench_*.py 纳入收集（_common.py / summarize.py 不匹配前缀，天然排除）。"""
    if file_path.suffix == ".py" and file_path.name.startswith("bench_"):
        return pytest.Module.from_parent(parent, path=file_path)
    return None
