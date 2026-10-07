"""W2-4 缺陷生成一期闭环 UIA 用例（PRD docs/prd-w2-4-flawgen-loop.md）。

DoD（roadmap W2-4）：选中目录跑生成引擎→产物落盘→可回标注页。
链路：缺陷生成页（OK 模板/缺陷库/输出目录/数量 2）→ 开始生成 →
"生成完成: 2 张" → 点「去标注」→ 标注页文件列表出现 synthetic_ 图名。

运行::

    .venv/Scripts/python.exe -m pytest tests/uia/test_flaw_gen_loop_w2_4.py -v -s --no-cov
"""
from __future__ import annotations

import logging
import os
import time

import pytest

try:
    from tests.uia.uia_helpers import (
        _iter_descendants,
        click_button,
        click_nav,
        enter_path_in_open_dialog,
        find_control_by_name,
        login_admin,
        read_status_text,
        set_spinner_value,
        wait_any_status,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        _iter_descendants,
        click_button,
        click_nav,
        enter_path_in_open_dialog,
        find_control_by_name,
        login_admin,
        read_status_text,
        set_spinner_value,
        wait_any_status,
    )

logger = logging.getLogger(__name__)

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_GEN = float(os.environ.get("AVA_UIA_T_GEN", "120"))


@pytest.fixture()
def gen_dirs(tmp_path_factory):
    """OK 模板 2 图 + 缺陷库 1 图（OpenCV 合成，离线）。"""
    import cv2
    import numpy as np

    base = tmp_path_factory.mktemp("w24_flaw")
    ok = base / "ok"
    flaw = base / "flaw"
    out = base / "out"
    ok.mkdir()
    flaw.mkdir()
    out.mkdir()
    for i in range(2):
        img = np.full((96, 96, 3), 120, np.uint8)
        img[20:40, 20:40] = 200
        cv2.imwrite(str(ok / f"ok{i}.png"), img)
    fl = np.full((96, 96, 3), 120, np.uint8)
    fl[50:70, 50:70] = 30  # 深色"缺陷"块
    cv2.imwrite(str(flaw / "defect0.png"), fl)
    return ok, flaw, out


def test_flaw_gen_to_label_loop(ready_admin_cfg, ava_app, gen_dirs):
    """W2-4 DoD：生成→落盘→去标注（最小链）。"""
    ok, flaw, out = gen_dirs
    win = ava_app
    login_admin(win)

    assert click_nav(win, "缺陷生成", T_NAV)
    time.sleep(1.0)

    # 三目录 + 数量 2（数量 spin 当前值默认 10）
    assert click_button(win, "浏览...", T_NAV)  # 首个浏览=OK 模板
    assert enter_path_in_open_dialog("选择 OK 模板目录", str(ok), T_NAV)
    time.sleep(0.8)
    # 缺陷数据库行浏览（树序第二个"浏览..."）
    browse = [
        c for c in _iter_descendants(win, max_depth=12)
        if type(c).__name__ == "ButtonControl" and "浏览" in (c.Name or "")
    ]
    assert len(browse) >= 3, f"应有 3 个目录浏览按钮，实得 {len(browse)}"
    browse[1].GetPattern(10000).Invoke()
    assert enter_path_in_open_dialog("选择缺陷数据库目录", str(flaw), T_NAV)
    time.sleep(0.8)
    browse[2].GetPattern(10000).Invoke()
    assert enter_path_in_open_dialog("选择合成图像输出目录", str(out), T_NAV)
    time.sleep(0.8)
    assert set_spinner_value(win, 2, expect_current=100, index=0), "数量设值失败"

    # ---- 生成 ----
    assert click_button(win, "开始生成", T_NAV)
    st = wait_any_status(win, ["缺陷生成完成", "生成失败"], T_GEN)
    assert st and "完成" in st, f"生成未成功: {st!r}"
    syn = sorted(out.glob("synthetic_*.png"))
    assert len(syn) >= 1, f"输出目录无合成图: {list(out.iterdir())[:5]}"
    logger.info("生成完成: %d 张", len(syn))

    # ---- 去标注（W2-4 核心新链）----
    btn = find_control_by_name(win, "去标注", ["ButtonControl"], T_NAV)
    assert btn is not None, "未找到「去标注」按钮"
    btn.GetPattern(10000).Invoke()
    deadline = time.time() + 20
    seen = None
    while time.time() < deadline:
        names = [
            (c.Name or "") for c in _iter_descendants(win, max_depth=12)
            if type(c).__name__ == "ListItemControl"
        ]
        hits = [n for n in names if "synthetic_" in n]
        if hits:
            seen = hits[0]
            break
        time.sleep(1.0)
    assert seen, f"标注页文件列表应出现 synthetic_ 图名，实见状态='{read_status_text(win)}'"
    logger.info("W2-4 DoD 链闭环: 生成 %d 张 → 去标注 → 列表见 %s",
                len(syn), seen)
