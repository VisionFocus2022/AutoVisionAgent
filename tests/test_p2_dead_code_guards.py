"""W14-C3 死代码守卫（v2 架构审查 P2-11①④）。

① models/supervised 曾导出 register_into_container——引用不存在的
core.dependency_injection，一旦调用必 ImportError（全仓 0 调用方，已删）；
④ run_m3_verification.py 曾调用不存在的 gui._render_preview 模块
（该验证步骤恒失败，已删除；离屏 GUI 构建由 M2 e2e 承担）。

守卫不变量：
- 公共导出（__all__）逐一真实存在（宣称即存在）；
- 死 DI 挂载函数不得回潮；
- 验证脚本引用的全部 `python -m <模块>` 入口可导入。
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_supervised_public_exports_all_resolve():
    """RED（P2-11①）：__all__ 里的名字必须真实可取，死导出不得回潮。"""
    import models.supervised as sv_pkg
    import models.supervised.registry as reg

    for name in sv_pkg.__all__:
        assert getattr(sv_pkg, name, None) is not None, (
            f"models.supervised 公共导出断链: {name}"
        )
    for name in reg.__all__:
        assert getattr(reg, name, None) is not None, (
            f"models.supervised.registry 公共导出断链: {name}"
        )
    # 引用不存在 core.dependency_injection 的死函数不得回潮
    assert "register_into_container" not in sv_pkg.__all__
    assert "register_into_container" not in reg.__all__
    assert not hasattr(sv_pkg, "register_into_container")
    assert not hasattr(reg, "register_into_container")


@pytest.mark.unit
def test_m3_verification_module_targets_importable():
    """RED（P2-11④）：验证脚本里所有 `python -m <模块>` 入口必须存在。

    此前第 4 步调用不存在的 gui._render_preview，验证脚本恒报失败。
    """
    src = (REPO_ROOT / "run_m3_verification.py").read_text(encoding="utf-8")
    targets = re.findall(r'sys\.executable,\s*"-m",\s*"([^"]+)"', src)
    assert targets, "应能从脚本中解析出 python -m 入口"
    missing = [m for m in targets if importlib.util.find_spec(m) is None]
    assert not missing, f"run_m3_verification 引用了不存在的模块入口: {missing}"
