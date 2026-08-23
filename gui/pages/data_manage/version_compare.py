"""版本对比摘要文本（W19 FR-4.2 功能体）。

W39·v6 P3：data_manage/page.py 触发页面规模守卫（≤800 行）第三次
拦截后的既定动作——自页面抽出纯格式化函数，页面保留薄委托方法
（测试缝 `_version_diff_text` 不变）。
"""
from __future__ import annotations

from gui.core.i18n import tr

# W19 FR-4.2：版本对比对话框每类示例上限（长清单只列前 20 条，计数仍全量）
_MAX_DIFF_EXAMPLES = 20


def version_diff_text(diff: dict) -> str:
    """diff 三类 → 摘要文本：各类计数 + 每类前 _MAX_DIFF_EXAMPLES 条示例。"""
    lines = []
    for key, label in (
        ("added", "新增"), ("removed", "删除"), ("changed", "变更"),
    ):
        items = diff.get(key, [])
        lines.append(f"{tr(label)} {len(items)} {tr('项')}")
        lines.extend(f"  {p}" for p in items[:_MAX_DIFF_EXAMPLES])
        if len(items) > _MAX_DIFF_EXAMPLES:
            lines.append(
                f"  {tr('……其余')} {len(items) - _MAX_DIFF_EXAMPLES} {tr('项略')}"
            )
    return "\n".join(lines)
