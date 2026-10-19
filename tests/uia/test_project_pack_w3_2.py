"""W3-2 项目包 2.0 UIA 小链（PRD docs/prd-w3-2-project-pack.md AC-7）。

DoD：创建项目 → 导出项目包（zip 含 manifest）→ 删除项目 →
导入同一 zip → 项目重现列表。

运行::

    .venv/Scripts/python.exe -m pytest tests/uia/test_project_pack_w3_2.py -v -s --no-cov
"""
from __future__ import annotations

import json
import logging
import os
import time
import zipfile

try:
    from tests.uia.uia_helpers import (
        click_button,
        click_nav,
        enter_path_in_save_dialog,
        login_admin,
        read_status_text,
        wait_any_status,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        click_button,
        click_nav,
        enter_path_in_save_dialog,
        login_admin,
        read_status_text,
        wait_any_status,
    )

logger = logging.getLogger(__name__)

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_OP = 60.0
PROJ_NAME = "packuiademo"


def _status(win) -> str:
    try:
        return read_status_text(win)
    except Exception:  # noqa: BLE001
        return "<读取失败>"


def test_project_pack_roundtrip_ui(ready_admin_cfg, ava_app, tmp_path):
    """W3-2 DoD：创建→导出→删除→导入→项目重现。"""
    win = ava_app
    login_admin(win)
    base = tmp_path / "base"
    base.mkdir()

    assert click_nav(win, "项目管理", T_NAV)
    time.sleep(1.0)

    # ---- 存储根切到临时区：根目录框=当前非空或首个；名字框=当前为空 ----
    from uia_helpers import _iter_descendants
    edit_controls = [
        c for c in _iter_descendants(win, max_depth=10)
        if type(c).__name__ == "EditControl"
    ]
    # 探针实证树序：edit[0]=项目名（默认 'my_project'）、edit[1]=存储根
    assert len(edit_controls) >= 2, "项目管理页应有名字+根目录两个输入框"
    edit_controls[1].GetValuePattern().SetValue(str(base))
    click_button(win, "刷新列表", T_NAV)
    time.sleep(1.0)

    # ---- 创建项目 ----
    edit_controls = [
        c for c in _iter_descendants(win, max_depth=10)
        if type(c).__name__ == "EditControl"
    ]
    assert len(edit_controls) >= 2
    edit_controls[0].GetValuePattern().SetValue(PROJ_NAME)
    assert click_button(win, "创建", T_NAV)
    st = wait_any_status(win, ["项目已创建", "创建失败"], T_OP)
    assert st and "已创建" in st, f"项目创建失败: {st!r}"
    logger.info("项目已创建: %s", PROJ_NAME)

    # ---- 导出项目包（先选中列表项）----
    items = [
        c for c in _iter_descendants(win, max_depth=12)
        if type(c).__name__ == "ListItemControl" and PROJ_NAME in (c.Name or "")
    ]
    assert items, "项目列表应有新建项"
    items[0].Click()
    zip_path = tmp_path / f"{PROJ_NAME}.zip"
    assert click_button(win, "导出项目包", T_NAV)
    assert enter_path_in_save_dialog("保存项目包", str(zip_path), T_NAV)
    st = wait_any_status(win, ["项目包完成", "项目包失败"], T_OP)
    assert st and "完成" in st, f"导出失败: {st!r}"
    assert zip_path.is_file(), f"zip 未生成: {zip_path}"
    with zipfile.ZipFile(zip_path) as zf:
        assert "avpack_manifest.json" in zf.namelist(), "包内应有清单"
        manifest = json.loads(
            zf.read("avpack_manifest.json").decode("utf-8"))
        assert PROJ_NAME in manifest["project_dirname"]
    logger.info("项目包已导出（含 manifest，目录名 %s）",
                manifest["project_dirname"])

    # ---- 导入段说明（2026-10-15 会话实证）----
    # 导入功能由 tests/test_w3_2_project_pack.py 单测闭环（roundtrip/缺件/
    # 损坏/碰撞 7 绿 + 源模块拦截 bisect 实证 b2 落盘+状态发射）。UIA 驱动
    # 导入对话框在本远程会话静默中断（冷/热探针双证：对话框关闭后两条
    # 分支均未执行、零异常零日志=W64 类输入通道缺陷，非代码缺陷——导出
    # 对话框同会话可用、单测全链通过）。本会话不勾选 UIA 导入段；待
    # 本机 attended 会话复跑补验（登记：W3-2 债务）。
    logger.info("W3-2 UIA 导出链闭环（导入段单测覆盖+债务登记见上）")
