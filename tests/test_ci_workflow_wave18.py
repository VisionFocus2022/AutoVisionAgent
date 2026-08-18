"""W18 簇 F（TASK-007 / FR-007）：ci.yml 就绪性守卫——pip cache、dotnet job、注释。

被测对象：.github/workflows/ci.yml（待命文件——本仓当前无 git 远程，推送后
生效）。与 W15 的 test_ci_workflow_file.py 互补：那侧守最小骨架不漂移，本侧
守 v3 P2-4 升级点不被误删：

- setup-python 开启 ``cache: 'pip'``（cu121 轮子约 2.5GB 为最大下载耗时项），
  且缓存键依赖文件指向 requirements.lock.txt——安装真源是锁文件，默认 glob
  会命中根目录松散 requirements.txt，lock 变更却不翻转缓存键→陈旧缓存；
- 新增 dotnet-test job：runs-on windows-latest（自带 .NET 8 SDK，无需
  setup-dotnet），checkout 后 ``dotnet test serving/dotnet_client``（与本地
  ``cd serving/dotnet_client && dotnet test`` 等效——该目录恰含一个 csproj，
  Tests/ 子目录同在其中）；
- 注释：文件头注明首跑前置（待 git remote 接入后首次生效，v3 P2-4）；python
  job 头部说明 lock 钉 torch==2.5.1+cu121 的 cu121/cpu 索引权衡与 pip cache
  缓解（换 cpu 索引装不出 +cu121 本地标签）。

真实首跑属用户侧动作（接入 git remote 后），不在本簇验收内——故本模块只做
静态结构断言，不尝试执行 workflow。
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # lock 已钉 PyYAML==6.0.3；缺失则跳过而非误报

CI_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci_doc() -> dict:
    assert CI_PATH.is_file(), f"CI workflow 缺失: {CI_PATH}"
    with open(CI_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def ci_text() -> str:
    return CI_PATH.read_text(encoding="utf-8")


def _find_step(job: dict, *, uses: str | None = None, run_contains: str | None = None) -> dict:
    for s in job.get("steps", []):
        if uses is not None and s.get("uses", "").startswith(uses):
            return s
        if run_contains is not None and run_contains in s.get("run", ""):
            return s
    pytest.fail(f"未找到步骤 uses={uses!r} run~={run_contains!r}")


def test_setup_python_enables_pip_cache(ci_doc):
    setup = _find_step(ci_doc["jobs"]["test"], uses="actions/setup-python")
    assert setup["with"].get("cache") == "pip"
    # 缓存键必须挂锁文件：默认 glob（**/requirements.txt）会命中根目录松散
    # requirements.txt，仅动 lock 时不翻转缓存键，缓存与安装真源脱钩。
    assert setup["with"].get("cache-dependency-path") == "requirements.lock.txt"


def test_dotnet_job_runs_dotnet_test_on_windows(ci_doc):
    job = ci_doc["jobs"]["dotnet-test"]
    assert job["runs-on"] == "windows-latest"
    _find_step(job, uses="actions/checkout@")
    _find_step(job, run_contains="dotnet test serving/dotnet_client")


def test_dotnet_job_uses_preinstalled_dotnet_sdk(ci_doc):
    """windows-latest 自带 .NET 8 SDK——不引入 actions/setup-dotnet 步骤。"""
    steps = ci_doc["jobs"]["dotnet-test"]["steps"]
    assert all("setup-dotnet" not in s.get("uses", "") for s in steps)


def test_comments_explain_first_run_prereq_and_torch_lock(ci_text):
    # 文件头：首跑前置（git remote 接入后首次生效）
    assert "v3 P2-4" in ci_text
    # python job 头部：cu121/cpu 索引权衡 + pip cache 缓解说明
    assert "torch==2.5.1+cu121" in ci_text
    assert "cpu" in ci_text
    assert "2.5GB" in ci_text
