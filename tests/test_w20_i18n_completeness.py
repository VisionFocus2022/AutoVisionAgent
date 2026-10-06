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


def _mode_label_keys() -> set:
    """解析 page.py _MODES 字面量表的 label_key（W44·A：变量键消费面收口）。

    模式按钮文案经 tr(label_key) 变量传入——字面量扫描永不覆盖；
    _MODES 为静态字面量表，可源码级枚举（非白名单维护）。
    """
    src = (REPO_ROOT / "gui" / "pages" / "label" / "page.py").read_text(
        encoding="utf-8"
    )
    m = re.search(r"_MODES = \[(.*?)\]", src, re.S)
    assert m, "_MODES 表未找到——结构变更须同步本守卫"
    return set(re.findall(r'"([^"]+)",\s*"[QRPKIJB]"', m.group(1)))


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
    assert any(k == "登录" for k in literals), "已知高频串未扫到"
    assert any(k == "旧" for k in literals), "单引号字面量未扫到（W38 口径）"


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


@pytest.mark.unit
def test_mode_label_keys_have_dict_entries():
    """W44·A：_MODES 全部 label_key 须在 _EN_US（变量键盲区收口）。"""
    missing = _mode_label_keys() - _dict_keys()
    assert not missing, (
        f"模式按钮变量键缺词条（en_US 露中文）：{sorted(missing)}"
    )


# ============================== W57·v7 P3-9：反向死键守卫（增量冻结） ============================== #
# 字典键 ∖（tr() 字面量 ∪ _MODES 变量键 ∪ 豁免清单）= 空集。
# 存量 66 键冻结于 _DEAD_KEY_ALLOWLIST（多数为动态链消费——pick_directory
# 参数经变量透传 tr()、状态栏载荷拼装等，扫描器不可见；少量硬死键留待
# 人工清理）。**棘轮语义：只减不增**——新增键若无消费面，本守卫即红，
# 防字典无界膨胀（v6 P3-9 由 407 键长到 424 键时无人察觉的通道）。
_DEAD_KEY_ALLOWLIST = frozenset({
    "...", "AutoVisionAgent", "ONNX", "SAM 全图", "SKolpha 复刻平台",
    "TensorRT", "关键点 (pose)", "分割 (seg)", "分类 (cls)",
    "切割完成", "切换主题", "切换语言", "划分完成", "删除完成", "单类",
    "实例分割", "实例分割 (pseg)", "导入完成",
    "将复制图像到 train/val/test 子目录（保留原文件）。确认？",
    "工程师", "已撤销", "已重做", "平均值", "异常检测 (abdet)",
    "引擎未安装：训练将使用模拟策略（假 loss，仅供流程验证）",
    "快捷键", "感知损失", "拖拽划定区域，区域内点击分割", "操作员",
    "文字识别", "无评估数据", "替换完成", "最大化", "最小化",
    "未选择图像", "标注画布", "检测 (det)", "生成质量", "管理员",
    "缺陷生成 (sgan)", "翻转完成", "菜单", "角色",
    "评估引擎不可用，退化为 GT 自比较（指标仅供参考）",
    "该任务引擎未安装", "语义分割", "语义分割 (sseg)",
    "请先选择标注文件夹", "超分辨率", "超分辨率 (super)", "还原",
    "选择图像", "选择存储目录", "选择导入源目录", "选择导出输出目录",
    "选择工作空间", "选择批量推理目录",
    "选择数据目录", "选择标注文件夹", "选择模型", "选择模型权重",
    "选择视频", "选择许可证文件", "（未装引擎）", "（模拟）",
    # W1-2：历史页表头经 tr(c) 列名循环动态消费（扫描器不可见）
    "操作", "状态",
    # W1-3：populate_task_combo 经参数默认值透传 tr()（动态链，扫描器不可见）
    "（模拟训练）",
    "该任务暂未实装真训练：训练为模拟策略（假 loss，仅供流程验证）",
})


@pytest.mark.unit
def test_no_new_dead_dict_keys():
    """反向死键守卫（W57·v7 P3-9）：新增字典键必须有消费面（棘轮只减不增）。"""
    consumed = set(_tr_literals()) | _mode_label_keys()
    dead = _dict_keys() - consumed - _DEAD_KEY_ALLOWLIST
    assert not dead, (
        f"新增死键 {len(dead)} 个（字典键无任何 tr() 消费面——请补消费、"
        f"删除键、或经复核加入豁免清单并注明动态链）：\n"
        + "\n".join(f"  {k!r}" for k in sorted(dead))
    )


@pytest.mark.unit
def test_dead_key_allowlist_ratchets_down():
    """豁免清单棘轮：清单键若已获消费面，必须从清单移除（防清单腐化）。"""
    consumed = set(_tr_literals()) | _mode_label_keys()
    stale = _DEAD_KEY_ALLOWLIST & consumed
    assert not stale, (
        f"豁免清单内 {len(stale)} 键已获字面量消费面，应从清单移除：{sorted(stale)}"
    )
