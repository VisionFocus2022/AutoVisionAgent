"""AUTO（SAM 全图概念分割）模式 UI 入口守卫（W46·B · TDD）。

取证背景：W44 加入 AUTO/AMG 通道时未挂工具栏按钮——_sam_attach 的
AUTO 分支 UI 不可达（死路）。本守卫锁住「AUTO 必须有模式按钮入口」，
防再次失联。
"""
from __future__ import annotations

from labeling.base import AnnotationMode


def test_auto_mode_has_toolbar_entry():
    """_MODES 必须含 AUTO 条目（SAM 全图按钮）。"""
    from gui.pages.label.page import _MODES

    autos = [entry for entry in _MODES if entry[0] is AnnotationMode.AUTO]
    assert len(autos) == 1, (
        f"_MODES 应恰含 1 个 AUTO 条目，实际 {len(autos)}：{[e[1] for e in _MODES]}"
    )
    mode, text, key = autos[0]
    assert text, "AUTO 按钮文本不得为空"
    assert len(key) == 1 and key.isalpha(), f"AUTO 快捷键应为单字母，实际 {key!r}"


def test_mode_shortcuts_unique():
    """模式快捷键不得与页内翻页/预标注键冲突（A=上一张 D=下一张 W=AI 预标注）。"""
    from gui.pages.label.page import _MODES

    keys = [k for _m, _t, k in _MODES] + ["A", "D", "W", "Space"]
    assert len(keys) == len(set(keys)), f"快捷键冲突: {sorted(keys)}"


def test_auto_in_sam_and_draw_modes():
    """AUTO 在 _SAM_MODES（触发 _ensure_sam）与 _DRAW_MODES（NoDrag 画布）中。"""
    from gui.pages.label.page import _DRAW_MODES, _SAM_MODES

    assert AnnotationMode.AUTO in _SAM_MODES
    assert AnnotationMode.AUTO in _DRAW_MODES
