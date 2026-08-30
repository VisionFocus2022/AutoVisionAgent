"""W24（v4 P3-1/P3-6）：文件级与函数级规模守卫——全生产包。

v4 第二波 #4：既有守卫（tests/test_w18_metrics_ast.py）只锁
evaluation/metrics_supervised.py 单文件的函数长度；本守卫把定义域扩到
pytest.ini --cov 声明的全部生产包（12 包，与覆盖率门禁口径同源、
解 pytest.ini 动态取得——新增 cov 包自动纳入守卫）：

- 文件级：物理行数 ≤800（编码规范上限）。现存违例按 v4 §9 棘轮先设
  850 再收敛 800：gui/pages/label/page.py 实测 828。棘轮条目自带
  失效断言——文件降到 800 以下后条目必须删除（守卫会红），保证只
  收紧不放松。
- 函数级：AST 度量（end_lineno-lineno+1，与 W18 守卫同口径）≤100；
  豁免清单带逐项数值上限——core.interfaces_supervised.
  _extract_state_dict_safe 上限 220（v4 第二波 #5：形态豁免声明补
  上限，超出须复审拆分）。豁免条目同样自带失效断言。
"""
import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

MAX_FILE_LINES = 800
MAX_FUNCTION_LINES = 100

# 棘轮（v4 §9「先设 850 再收敛」）：现存超 800 文件的临时上限——
# 只许降不许升；文件降到 800 以下后由下方失效断言强制删除条目。
# W27：gui/pages/label/page.py 828→695（SAM 会话+预标注 worker 抽出），
# 条目已按失效断言删除——label 页回归 ≤800 常规管辖。
FILE_RATCHET = {}

# 豁免（v4 P3-6）：函数级超限的有意豁免——值=复审线，超出必须拆分；
# 函数降到 100 以下后由下方失效断言强制删除条目。
FUNCTION_EXEMPTIONS = {
    ("core/interfaces_supervised.py", "AbstractTaskEngine._extract_state_dict_safe"): 220,
}


def _cov_packages() -> list:
    """从 pytest.ini addopts 解析 --cov 源（守卫定义域与覆盖率口径同源）。

    W24 对抗验证员 low 加固：同时接受等号与空格形态，并断言解析数与
    --cov 出现次数一致——pytest.ini 混入路径等非标识符形态时守卫定义域
    会与覆盖率域静默漂移，此处宁可红不可漏。"""
    text = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    pkgs = re.findall(r"--cov[=\s]+([A-Za-z_][\w.]*)", text)
    total = len(re.findall(r"--cov[=\s](?!\S*[=-])", text))
    assert pkgs, "pytest.ini 未解析到 --cov 源——守卫定义域失效"
    assert len(pkgs) == total, (
        f"--cov 出现 {total} 次但仅解析到 {len(pkgs)} 个标识符源"
        f"（存在空格/路径形态）——守卫域与覆盖率域将漂移，须人工对齐"
    )
    return pkgs


def _iter_production_py_files():
    for pkg in _cov_packages():
        d = REPO_ROOT / pkg
        assert d.is_dir(), f"--cov 源目录不存在: {pkg}"
        yield from sorted(d.rglob("*.py"))


def _iter_functions(path: Path):
    """产出 (限定名, AST 节点)——类方法得 Class.method、嵌套得 a.b。"""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                yield name, child
                yield from walk(child, name)
            elif isinstance(child, ast.ClassDef):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                yield from walk(child, qual)
            else:
                yield from walk(child, prefix)

    yield from walk(tree)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


@pytest.mark.unit
def test_all_production_files_within_800_lines():
    """全生产包 .py 物理行数 ≤800（棘轮文件按临时上限，收敛目标 800）。"""
    offenders = []
    for p in _iter_production_py_files():
        rel = p.relative_to(REPO_ROOT).as_posix()
        n = _line_count(p)
        limit = FILE_RATCHET.get(rel, MAX_FILE_LINES)
        if n > limit:
            offenders.append(f"{rel}: {n} > {limit}")
    assert not offenders, f"文件规模超限（v4 P3-1）: {offenders}"


@pytest.mark.unit
def test_file_ratchet_entries_are_active_violations():
    """棘轮卫生：条目必须仍是真实违例（>800），否则条目已失效须删除。

    这是棘轮的收紧机制：gui/pages/label/page.py 一旦降到 800 以下，
    本断言变红，强制删掉 FILE_RATCHET 条目——全局上限随之收紧到位。
    """
    stale = []
    for rel in FILE_RATCHET:
        n = _line_count(REPO_ROOT / rel)
        if n <= MAX_FILE_LINES:
            stale.append(f"{rel}: 现仅 {n} 行 ≤{MAX_FILE_LINES}，删棘轮条目")
    assert not stale, f"棘轮条目失效（文件已收敛，条目须删）: {stale}"


@pytest.mark.unit
def test_all_production_functions_within_100_lines():
    """全生产包函数/方法 AST 度量 ≤100；豁免条目按各自上限（超出须复审拆分）。"""
    offenders = []
    for p in _iter_production_py_files():
        rel = p.relative_to(REPO_ROOT).as_posix()
        for name, node in _iter_functions(p):
            length = node.end_lineno - node.lineno + 1
            cap = FUNCTION_EXEMPTIONS.get((rel, name))
            if cap is not None:
                if length > cap:
                    offenders.append(
                        f"{rel}::{name}: {length} > 豁免上限 {cap}（须复审拆分）"
                    )
            elif length > MAX_FUNCTION_LINES:
                offenders.append(
                    f"{rel}::{name}: {length} > {MAX_FUNCTION_LINES}（无豁免）"
                )
    assert not offenders, f"函数规模超限（v4 P3-1/P3-6）: {offenders}"


@pytest.mark.unit
def test_function_exemptions_are_active_violations():
    """豁免卫生：条目必须仍是真实违例（>100），否则条目已失效须删除。"""
    stale = []
    for rel, name in FUNCTION_EXEMPTIONS:
        path = REPO_ROOT / rel
        found = {
            n: nd.end_lineno - nd.lineno + 1
            for n, nd in _iter_functions(path)
            if n == name
        }
        if not found:
            stale.append(f"{rel}::{name}: 函数不存在（改名/删除后须同步豁免表）")
        elif next(iter(found.values())) <= MAX_FUNCTION_LINES:
            stale.append(
                f"{rel}::{name}: 现仅 {next(iter(found.values()))} 行，删豁免条目"
            )
    assert not stale, f"豁免条目失效（函数已收敛，条目须删）: {stale}"


@pytest.mark.unit
def test_extract_state_dict_safe_exemption_declares_cap():
    """v4 P3-6：形态豁免声明须含数值上限 220（超出须复审拆分）。

    W24 前声明只写"约 195 行"近似值且无数值约束——本守卫把上限
    数值化钉进声明文本，与 FUNCTION_EXEMPTIONS 的 220 同源。
    """
    src = (REPO_ROOT / "core" / "interfaces_supervised.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r"形态豁免声明", src), "豁免声明标记被删（W18 守卫同锚）"
    assert re.search(r"上限\s*220\s*行", src), (
        "形态豁免声明未数值化上限（v4 P3-6：补『上限 220 行，超出须复审拆分』）"
    )
