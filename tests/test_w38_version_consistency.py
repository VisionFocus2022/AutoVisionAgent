"""版本四方一致性守卫（v6 P1-2 收口，W38）。

背景：v2.1.0 发版时 README/RELEASES/settings 已升 2.1.0 而 pyproject
停在 2.0.0（v6 深审 P1-2 实测），且无任何机械守卫锁定版本宣称——
RELEASES 所称「五方打包一致性守卫」实为动态导入守卫，与版本无关。

口径：提取四处版本串并断言一致——
  README.md                    ``# AutoVisionAgent <ver>``
  RELEASES.md                  首个 ``## v<ver>``（最新条目）
  gui/pages/settings/page.py   ``v<ver> (M<n>)``
  pyproject.toml               ``version = "<ver>"``
git tag 不在断言内（tag 属发布动作，由收尾门禁裁决）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _first(pattern: str, rel: str) -> str:
    m = re.search(pattern, _read(rel), re.M)
    assert m, f"{rel} 未匹配到版本串（模式 {pattern!r}）——文件结构变更须同步本守卫"
    return m.group(1)


@pytest.mark.unit
def test_four_way_version_consistency():
    """README / RELEASES / settings 关于页 / pyproject 四处版本必须一致。"""
    versions = {
        "README.md": _first(r"^# AutoVisionAgent (\d+\.\d+\.\d+)", "README.md"),
        "RELEASES.md": _first(r"^## v(\d+\.\d+\.\d+)", "RELEASES.md"),
        "settings/page.py": _first(r"v(\d+\.\d+\.\d+) \(M\d\)", "gui/pages/settings/page.py"),
        "pyproject.toml": _first(r'^version = "(\d+\.\d+\.\d+)"', "pyproject.toml"),
    }
    distinct = set(versions.values())
    assert len(distinct) == 1, f"版本宣称不一致（发版四处必同步）：{versions}"
