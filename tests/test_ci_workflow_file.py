"""GitHub Actions CI workflow 文件存在性与关键步骤测试（架构审查 P2-26 收尾）。

被测对象：.github/workflows/ci.yml（待命文件——本仓当前无 git 远程，推送后
生效）。断言其与本地 .venv 构建方式一致的最小骨架不被误删/漂移：

- YAML 可解析；
- windows-latest 运行器 + checkout@v4 + setup-python 3.11；
- 依赖安装来自 requirements.lock.txt（全量锁装，非松散 requirements.txt）；
- 运行 ``python -m pytest``（覆盖率门禁 fail-under=92 由 pytest.ini 生效，
  CI 不另行传覆盖率参数）；
- QT_QPA_PLATFORM=offscreen 环境变量在场（无头 runner 上 Qt 离屏）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # venv 已有 pyyaml 6.0.3；缺失则跳过而非误报

CI_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci_doc() -> dict:
    assert CI_PATH.is_file(), f"CI workflow 缺失: {CI_PATH}"
    with open(CI_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _steps(job: dict) -> list[dict]:
    return job.get("steps", [])


def _find_step(steps: list[dict], *, uses: str | None = None, run_contains: str | None = None) -> dict:
    for s in steps:
        if uses is not None and s.get("uses", "").startswith(uses):
            return s
        if run_contains is not None and run_contains in s.get("run", ""):
            return s
    pytest.fail(f"未找到步骤 uses={uses!r} run~={run_contains!r}")


def test_runs_on_windows_latest(ci_doc):
    job = ci_doc["jobs"]["test"]
    assert job["runs-on"] == "windows-latest"


def test_checkout_and_python_setup(ci_doc):
    steps = _steps(ci_doc["jobs"]["test"])
    # v5/v6（2026-08-18 CI 首跑后升级，消 Node20 弃用警告）
    _find_step(steps, uses="actions/checkout@v5")
    setup = _find_step(steps, uses="actions/setup-python")
    assert str(setup["with"]["python-version"]) == "3.12"


def test_deps_installed_from_lock(ci_doc):
    steps = _steps(ci_doc["jobs"]["test"])
    install = _find_step(steps, run_contains="pip install -r requirements.lock.txt")
    assert "requirements.txt\n" not in install["run"]  # 不是松散 requirements.txt


def test_pytest_plain_command_with_offscreen(ci_doc):
    steps = _steps(ci_doc["jobs"]["test"])
    gate = _find_step(steps, run_contains="python -m pytest")
    assert gate.get("env", {}).get("QT_QPA_PLATFORM") == "offscreen"
