"""i18n 完整性机械守卫（v5 P2-N3 收口：tr() 字面量 ∖ 字典键 = 空集）。

回归背景：v5 复审机械对账发现 27 处 tr() 缺词条（26 存量 + W31 AMP 1 处
——后者根因是词条添加 shell 命令 `||` 短路未执行，ch 中文回退源串直出
掩盖漏翻、门禁不红）。W20「tr()+zh/en 同 commit」教义此前无机械守卫。

口径声明：覆盖 tr("纯字面量") 与 tr('纯字面量') 双引号+单引号两种形态
（W38·P2-5 起含单引号；f-string/变量键不在内）——缺失计数为下界；
新增 UI 文案应同时扩本守卫覆盖面。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = REPO_ROOT / "gui"
I18N_FILE = GUI_ROOT / "core" / "i18n.py"


def _dict_keys() -> set:
    """提取 _EN_US 字典全部键（4 空格缩进的 "..." 行，源文本原样）。

    W38·P1-1：删除原「\\\\→\\ 归一化」——其宣称「运行时两者等价」已被
    运行时复现证伪（源文件双反斜杠键在运行时永不匹配 tr() 查询串）。
    字面量与键现按源文本严格比对；双反斜杠写法由
    test_dict_keys_have_no_double_backslash 显式拒绝。
    """
    src = I18N_FILE.read_text(encoding="utf-8")
    keys = re.findall(r'^\s{4}"([^"]+)":', src, re.M)
    return set(keys)


def _tr_literals() -> dict:
    """扫描 gui 包全部 tr("…")/tr('…') 字面量调用 → {串: [文件名…]}。"""
    hits: dict = {}
    for py in GUI_ROOT.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in (r'\btr\("([^"]+)"\)', r"\btr\('([^']+)'\)"):
            for m in re.findall(pattern, src):
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
    assert any("旧" == k for k in literals), "单引号字面量未扫到（W38 口径）"


@pytest.mark.unit
def test_dict_keys_have_no_double_backslash():
    """字典键源文本不得含双反斜杠（W38·P1-1 回归守卫）。

    `\\n` 写法的键运行时为「反斜杠+n」两字符，永不匹配调用点 `\n`
    （真实换行）的查询串——en_US 模式漏翻；原归一化已删，此类写法
    在此显式拒绝（历史实例：i18n.py 退出确认键，v6 P1-1）。
    """
    src = I18N_FILE.read_text(encoding="utf-8")
    raw_keys = re.findall(r'^\s{4}"([^"]+)":', src, re.M)
    bad = [k for k in raw_keys if "\\\\" in k]
    assert not bad, (
        f"字典键源文本含双反斜杠转义（运行时永不匹配 tr 调用，"
        f"en_US 将漏翻）：{bad}"
    )


@pytest.mark.unit
def test_runtime_lookup_hits_newline_escaped_key():
    """运行时命中：含真实换行的查询串必须查到词条（W38·P1-1）。"""
    from gui.core.i18n import _EN_US, current_language, set_language, tr

    prev = current_language()
    set_language("en_US")
    try:
        s = "有正在进行的操作（训练/推理）。\n"
        assert s in _EN_US, "转义键缺失：调用点查询串未入字典"
        assert tr(s) != s, "tr() 回退源串：翻译未生效"
    finally:
        set_language(prev)
