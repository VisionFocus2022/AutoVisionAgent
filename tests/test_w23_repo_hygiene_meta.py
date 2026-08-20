"""W23（v4 P2-1）：仓库卫生与敏感边界——元守卫。

防 W19 式复发（initial_credentials.txt 引入时漏配 .gitignore）：
① .gitignore 必须含 5 个收口模式串（瞬态工具产物 ×4 + 明文凭据文件 ×1）；
② 瞬态/工具产物必须不再被 git 跟踪（W23 前 9 个文件在索引——
.autofix-loop/×6、.benchmarks/wave19-raw.json、_i18n_report.txt、
_missing_keys.txt）。

镜像 tests/test_w19_benchmarks_meta.py / test_uia_helpers_guard.py 的
元守卫手法：不进覆盖分母（tests/ 不在 --cov 列表），只锁仓库形态。
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_PATTERNS = (
    ".autofix-loop/",
    "_i18n_report.txt",
    "_missing_keys.txt",
    ".benchmarks/",
    "configs/initial_credentials.txt",
)


@pytest.mark.unit
def test_gitignore_contains_hygiene_patterns():
    """5 个收口模式串逐一在 .gitignore 文本中（W23 前 5 条全缺）。"""
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    missing = [p for p in _PATTERNS if p not in text]
    assert not missing, f".gitignore 缺少收口条目: {missing}"


@pytest.mark.unit
def test_transient_artifacts_not_tracked():
    """瞬态/工具产物不被 git 跟踪（W23 前 9 个文件在索引）。

    对抗验证员补充：pathspec 必须含 configs/initial_credentials.txt——
    它是安全最敏感目标（明文凭据），若被 git add -f 强制入库须在本守卫
    报警，不能只靠 .gitignore 文本断言间接兜底。
    """
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--",
         ".autofix-loop", ".benchmarks", "_i18n_report.txt", "_missing_keys.txt",
         "configs/initial_credentials.txt"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    tracked = [line for line in proc.stdout.splitlines() if line.strip()]
    assert tracked == [], f"瞬态产物仍被跟踪: {tracked}"
