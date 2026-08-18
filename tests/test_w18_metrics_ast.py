"""W18 簇 D（TASK-005 / v3 P2-10）形态守卫。

- ``evaluation/metrics_supervised.py``：det_map 拆分后，全部函数/方法
  行数 ≤100（AST 度量：end_lineno - lineno + 1，含签名与 docstring）；
- ``core/interfaces_supervised.py``：``_extract_state_dict_safe`` 保留
  "形态豁免声明"——约 195 行函数+嵌套 RestrictedUnpickler 安全类的
  有意豁免（v3 P2-10 架构审查裁定保持整块），防止后人误拆或误删声明。

纯重构数值零变化由 tests/test_eval_flow.py（0.5455/1.0000 锚）与
tests/test_metrics_supervised.py 承担，本文件只守形态。
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
METRICS_PATH = REPO_ROOT / "evaluation" / "metrics_supervised.py"
INTERFACES_PATH = REPO_ROOT / "core" / "interfaces_supervised.py"

MAX_FUNCTION_LINES = 100


def _collect_function_lengths(tree: ast.Module) -> list:
    """递归收集 (限定名, 起始行, 行数)；覆盖函数、异步函数与方法。"""
    out = []

    def _walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                length = child.end_lineno - child.lineno + 1
                out.append((name, child.lineno, length))
                _walk(child, prefix=f"{name}.")
            elif isinstance(child, ast.ClassDef):
                _walk(child, prefix=f"{prefix}{child.name}.")
            else:
                _walk(child, prefix=prefix)

    _walk(tree, prefix="")
    return out


@pytest.mark.unit
def test_metrics_supervised_all_functions_within_100_lines():
    """metrics_supervised.py 全部函数/方法 ≤100 行（det_map 拆分守卫）。"""
    tree = ast.parse(METRICS_PATH.read_text(encoding="utf-8"))
    lengths = _collect_function_lengths(tree)
    assert lengths, "未解析到任何函数，AST 守卫失效"
    over = [(n, ln) for n, _, ln in lengths if ln > MAX_FUNCTION_LINES]
    assert not over, (
        f"metrics_supervised.py 存在超过 {MAX_FUNCTION_LINES} 行的函数: "
        f"{over}（v3 P2-10：det_map 已按职责拆出单类收集与 11 点插值 AP）"
    )


@pytest.mark.unit
def test_extract_state_dict_safe_exemption_declaration_present():
    """_extract_state_dict_safe 的形态豁免声明（v3 P2-10）必须留痕。"""
    src = INTERFACES_PATH.read_text(encoding="utf-8")
    assert "形态豁免声明" in src, (
        "core/interfaces_supervised.py 缺少 '形态豁免声明'（v3 P2-10）："
        "_extract_state_dict_safe 约 195 行是有意豁免的安全整块，"
        "豁免声明不得被删除"
    )
