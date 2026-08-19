"""UIA uia_helpers.find_main_window 窗口消歧守卫（W21 打包验证期发现）。

背景：桌面存在同名顶层窗口（如用户打开的 dist\AutoVisionAgent Explorer
文件夹窗，CabinetWClass）时，Name-only 匹配按 UIA 枚举序错绑——整套
UIA 在文件夹窗口里找控件，6 用例确定性全挂。守卫：主窗口匹配必须
同时钉住应用窗口 ClassName，防回退到 Name-only。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("uiautomation")

_SRC = (Path(__file__).resolve().parents[1] / "tests" / "uia" / "uia_helpers.py").read_text(encoding="utf-8")


@pytest.mark.unit
def test_find_main_window_pins_class_name():
    """find_main_window 的窗口搜索必须含 ClassName（同名窗口消歧）。"""
    import re
    m = re.search(r"def find_main_window.*?WindowControl\(([^)]*)\)", _SRC, re.S)
    assert m, "find_main_window 内应有 ua.WindowControl( 搜索"
    args = m.group(1)
    assert "Name=" in args, "搜索参数应含 Name"
    assert "ClassName" in args, (
        f"窗口搜索必须钉住 ClassName 防同名顶层窗口错绑"
        f"（如 Explorer 文件夹窗 CabinetWClass），实际参数: {args!r}"
    )
