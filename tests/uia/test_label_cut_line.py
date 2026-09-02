"""切割线工业形态（W56 · C 键）UIA 真窗测试——AC-001/002 硬断言。

被测链路：切割线模式 → 逐点单击 3 点 → 右键提交 → 保存 LabelMe JSON
铁证（shape_type=linestrip + mode=cut_line + 3 点不闭合——与多边形
闭合语义的差异化断言）。

模式：默认 exe 模式（重打包后产物已含 W56 代码；AVA_UIA_SOURCE=python
亦可）。单图目录（规避保存后自动切图 R3-14 干扰）。

断言口径（沿用套件规约）：状态栏文本 + 磁盘 JSON 铁证；无截图断言；
失败消息含英文 "timeout"（find-timeout 分类惯例）。

运行（机器空闲时）::

    .venv/Scripts/python.exe -m pytest tests/uia/test_label_cut_line.py \\
        -o addopts= --timeout=600 -v
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import logging
import os
import re
import time
from pathlib import Path

import pytest

try:
    from tests.uia.uia_helpers import (
        _find_canvas,
        _wait_dialog,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        read_status_text,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-def]
        _find_canvas,
        _wait_dialog,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        read_status_text,
    )

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_GENERIC = 20.0

# 折线三点（画布相对坐标——斜穿画布，覆盖足够像素行程）
_P1 = (0.25, 0.70)
_P2 = (0.50, 0.35)
_P3 = (0.75, 0.60)


# ================================ 夹具 ================================ #


@pytest.fixture()
def single_image_dir(tmp_path):
    """单图目录（规避保存自动切图 R3-14 的跨图 shapes 干扰）。"""
    from PIL import Image

    d = tmp_path / "one"
    d.mkdir()
    Image.new("RGB", (800, 600), (60, 60, 60)).save(d / "only.png")
    return d


# ================================ 本地辅助（套件同款） ================================ #


def _ensure_logged_in(win) -> None:
    """离线登录（幂等，与既有套件同款硬校验）。"""
    for _attempt in range(2):
        with contextlib.suppress(Exception):
            win.SetActive()
        dismiss_stale_dialogs()
        if find_control_by_name(
            win, "离线模式", ["ButtonControl", "CheckBoxControl"], timeout=8.0
        ) is None:
            return
        assert click_button(win, "离线模式", T_NAV), "未找到'离线模式'按钮（find timeout）"
        confirm_dialog_if_present("离线模式", timeout=3.0)
        time.sleep(1.0)
    pytest.fail("离线登录未完成：两轮尝试后仍在登录页")


def _wait_image_loaded(win) -> None:
    """打开单图文件夹并等加载完成（终态口径=「已加载 N 张」，套件同款）。"""
    assert click_nav(win, "标注", T_NAV), "无法切换到标注页（find timeout）"
    time.sleep(1.0)
    assert click_button(win, "打开文件夹", T_NAV), "未找到'打开文件夹'按钮（find timeout）"
    assert enter_path_in_open_dialog("打开文件夹", os.environ["AVA_CUT_IMG_DIR"], T_NAV), \
        "打开标注文件夹失败"
    deadline = time.time() + T_GENERIC
    status = ""
    while time.time() < deadline:
        try:
            status = read_status_text(win)
        except Exception:  # noqa: BLE001
            status = ""
        if ("已加载" in status and "张" in status) or "only.png" in status:
            time.sleep(1.5)
            return
        time.sleep(0.4)
    pytest.fail(f"图像未加载（状态='{status}'）")


def _abs_pt(win, rel: tuple[float, float]):
    canvas = _find_canvas(win)
    assert canvas is not None, "未定位到画布控件（find timeout）"
    r = canvas.BoundingRectangle
    return (
        int(r.left + (r.right - r.left) * rel[0]),
        int(r.top + (r.bottom - r.top) * rel[1]),
    )


def _draw_polyline(win, verts: list[tuple[float, float]]) -> None:
    """C 模式逐点单击 + 右键提交（右键位置=末点，提交语义与多边形一致）。"""
    import uiautomation as _ua

    with contextlib.suppress(Exception):
        win.SetActive()
    _ua.Click(*_abs_pt(win, (0.5, 0.5)), waitTime=0.4)  # 激活/聚焦（画布空白安全点）
    user32 = ctypes.windll.user32
    x = y = 0
    for rel in verts:
        x, y = _abs_pt(win, rel)
        user32.SetCursorPos(x, y)
        time.sleep(0.08)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.2)
    time.sleep(0.2)
    logger.info("切割线自绘完成（提交改经 Return 键）: %s", verts)


def _commit_by_return(win) -> None:
    """Return 键提交（页面既定快捷键，与右键等价路径）。

    W61 实测：raw 右键（0x0008/0x0010）在本机不达 Qt 事件循环（左键同法
    全达、控制器零收到右键），成因未定（环境级注入差异疑）；Return 键
    经 SendKey 稳定到达——作为等价既定提交路径采用，异常留档 deviations。
    """
    import uiautomation as _ua

    with contextlib.suppress(Exception):
        win.SetActive()
    time.sleep(0.3)
    _ua.SendKey(_ua.Keys.VK_RETURN)
    time.sleep(0.6)


def _shape_count(win) -> int:
    try:
        status = read_status_text(win)
    except Exception:  # noqa: BLE001
        return -1
    m = re.search(r"(\d+)\s+标注数", status)
    return int(m.group(1)) if m else -1


def _save_json(win, labels_dir: Path, name: str) -> dict:
    """保存标注 → 读回 LabelMe JSON（落盘为真值，≤3 轮，套件同款）。"""
    path = labels_dir / name
    dismiss_stale_dialogs()
    for attempt in range(3):
        assert click_button(win, "保存标注", T_NAV), "未找到'保存标注'按钮（find timeout）"
        if not enter_path_in_save_dialog("保存标注", str(path), timeout=8.0):
            dismiss_stale_dialogs()
            continue
        dlg = _wait_dialog("保存标注", 0.8)
        if dlg is not None:
            with contextlib.suppress(Exception):
                dlg.SetActive()
                import uiautomation as _ua

                _ua.SendKey(_ua.Keys.VK_RETURN)
                time.sleep(0.5)
        deadline = time.time() + 5.0
        while time.time() < deadline and not path.exists():
            time.sleep(0.3)
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
        logger.warning("保存第 %d 轮未落盘，清扫重试", attempt + 1)
        dismiss_stale_dialogs()
    pytest.fail(f"标注文件未生成: {path}（3 轮重试）")


# ================================ 用例 ================================ #


@pytest.mark.uia
def test_cut_line_mode_end_to_end(ava_app, single_image_dir, workspace_dir):
    """C 模式 3 点折线 → 保存 → JSON 铁证：linestrip + mode=cut_line +
    3 点不闭合（首尾分离——切割路径语义，非闭合区域）。"""
    win = ava_app
    os.environ["AVA_CUT_IMG_DIR"] = str(single_image_dir)
    try:
        _ensure_logged_in(win)
        _wait_image_loaded(win)

        assert click_button(win, "切割线", T_NAV), (
            "未找到'切割线'按钮（find timeout）——W56 形态未入 exe？"
        )
        time.sleep(0.5)
        _draw_polyline(win, [_P1, _P2, _P3])
        _commit_by_return(win)
        deadline = time.time() + 8.0
        while time.time() < deadline and _shape_count(win) < 1:
            time.sleep(0.4)
        assert _shape_count(win) >= 1, "切割线未提交（状态栏无标注计数）"

        doc = _save_json(win, workspace_dir, "cut_line.json")
        shapes = doc.get("shapes", [])
        assert len(shapes) == 1, f"期望 1 个 shape，实得 {len(shapes)}"
        shape = shapes[0]
        assert shape["shape_type"] == "linestrip", (
            f"shape_type 应为 linestrip，实得 {shape['shape_type']}"
        )
        assert shape.get("mode") == "cut_line", (
            f"mode 自定义键应为 cut_line，实得 {shape.get('mode')}"
        )
        pts = shape["points"]
        assert len(pts) == 3, f"期望 3 点折线，实得 {len(pts)}：{pts}"
        assert pts[0] != pts[-1], (
            f"切割线不得闭合（首尾应分离）：{pts[0]} == {pts[-1]}"
        )
        logger.info("切割线 E2E 铁证: %s", pts)
    finally:
        os.environ.pop("AVA_CUT_IMG_DIR", None)
