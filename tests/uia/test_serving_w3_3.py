"""W3-3 gRPC 服务页 UIA 最小链（PRD docs/prd-w3-3-serving.md AC-5）。

链路：服务页 → 启动服务 → 状态运行中 → 健康检查 → 回显（无原生
对话框=无 W64 类会话通道风险，全 Invoke 可达）。

运行::

    .venv/Scripts/python.exe -m pytest tests/uia/test_serving_w3_3.py -v -s --no-cov
"""
from __future__ import annotations

import logging
import os
import time

try:
    from tests.uia.uia_helpers import (
        click_button,
        click_nav,
        find_control_by_name,
        login_admin,
        read_status_text,
        wait_any_status,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        click_button,
        click_nav,
        find_control_by_name,
        login_admin,
        read_status_text,
        wait_any_status,
    )

logger = logging.getLogger(__name__)

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_SVC = 30.0


def test_serving_start_and_health(ready_admin_cfg, ava_app):
    """W3-3 DoD：启动→运行中→健康检查回显。"""
    win = ava_app
    login_admin(win)
    assert click_nav(win, "服务", T_NAV), "未找到「服务」导航"
    time.sleep(1.0)

    assert click_button(win, "启动服务", T_NAV)
    st = wait_any_status(win, ["服务已启动", "服务启动失败"], T_SVC)
    assert st and "已启动" in st, f"启动失败: {st!r}"
    state = find_control_by_name(win, "运行中", None, 10)
    assert state is not None, "状态标签应显示运行中"
    logger.info("服务已启动: %s", read_status_text(win))

    assert click_button(win, "健康检查", T_NAV)
    st = wait_any_status(win, ["健康检查通过", "健康检查失败"], T_SVC)
    assert st and "通过" in st, f"健康检查未通过: {st!r}"
    logger.info("W3-3 UIA 链闭环: %s", st)

    # 收尾：停止服务（保持进程干净）
    assert click_button(win, "停止服务", T_NAV)
    st = wait_any_status(win, ["服务已停止", "服务未运行"], T_SVC)
    assert st and "已停止" in st
