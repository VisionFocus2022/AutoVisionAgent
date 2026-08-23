"""i18n 完整性机械守卫（v5 P2-N3 收口：tr() 字面量 ∖ 字典键 = 空集）。

回归背景：v5 复审机械对账发现 27 处 tr() 缺词条（26 存量 + W31 AMP 1 处
——后者根因是词条添加 shell 命令 `||` 短路未执行，ch 中文回退源串直出
掩盖漏翻、门禁不红）。W20「tr()+zh/en 同 commit」教义此前无机械守卫。

口径声明：仅覆盖 tr("纯字面量") 形态（f-string/变量键不在内）——
缺失计数为下界；新增 UI 文案应同时扩本守卫覆盖面。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = REPO_ROOT / "gui"
I18N_FILE = GUI_ROOT / "core" / "i18n.py"


def _dict_keys() -> set:
    """提取 _EN_US 字典全部键（4 空格缩进的 "..." 行）。

    文本层归一：dict 行内转义序列写作 \\\\n（源文件双反斜杠），tr()
    调用行写作 \\n——对账前把 dict 键的 \\\\ 归一为 \\（运行时两者
    等价，仅源文件文本形态不同）。
    """
    src = I18N_FILE.read_text(encoding="utf-8")
    keys = re.findall(r'^\s{4}"([^"]+)":', src, re.M)
    return {k.replace("\\\\", "\\") for k in keys}


def _tr_literals() -> dict:
    """扫描 gui 包全部 tr("字面量") 调用 → {串: [文件名…]}。"""
    hits: dict = {}
    for py in GUI_ROOT.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.findall(r'\btr\("([^"]+)"\)', src):
            hits.setdefault(m, []).append(py.name)
    return hits


@pytest.mark.unit
def test_all_tr_literals_have_dict_entries():
    """每个 tr() 字面量在 _EN_US 必须有词条（en_US 模式零中文残留）。"""
    keys = _dict_keys()
    literals = _tr_literals()
    missing = {
        lit: sorted(set(files)) for lit, files in literals.items() if lit not in keys
    }
    assert not missing, (
        f"tr() 调用缺少 i18n 词条（en_US 模式将漏翻显示中文），共 "
        f"{len(missing)} 处：\n"
        + "\n".join(f"  {lit!r} ← {files}" for lit, files in sorted(missing.items()))
    )


@pytest.mark.unit
def test_scanner_actually_scans():
    """探针：守卫真的在扫（防止 rglob 失效静默空集假绿）。"""
    literals = _tr_literals()
    assert len(literals) > 50, f"扫描面异常（仅 {len(literals)} 个字面量）"
    assert any("登录" == k for k in literals), "已知高频串未扫到"
