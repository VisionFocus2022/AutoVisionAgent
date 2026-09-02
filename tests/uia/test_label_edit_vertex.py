"""标注编辑模式（W55 · E 键顶点编辑）UIA 真窗测试。

被测链路：多边形绘制 → 编辑模式选中（顶点手柄）→ 拖动顶点 → 保存
LabelMe JSON 对比铁证（编辑前后仅被拖顶点变化）。

模式：默认 exe 模式（W61 重打包后产物已含 W55 代码，按本文件原注
「重打包后可放开」解除仅源码守卫；AVA_UIA_SOURCE=python 亦可）。
单图目录（规避保存后自动切图 R3-14 的跨图 shapes 干扰）。

断言口径（沿用套件规约）：状态栏文本 + 磁盘 JSON 铁证；无截图断言。

运行（机器空闲时）::

    AVA_UIA_SOURCE=python .venv/Scripts/python.exe -m pytest \\
        tests/uia/test_label_edit_vertex.py -o addopts= --timeout=600 -v
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

# 三角形顶点/内部/拖动目标（画布相对坐标）
_V_A = (0.30, 0.30)   # 顶点 A（被拖动）
_V_B = (0.70, 0.30)
_V_C = (0.70, 0.70)
_INSIDE = (0.55, 0.42)  # 三角形质心附近（选中用）
_DRAG_TO = (0.44, 0.32)  # 拖动目标


# ================================ 夹具 ================================ #


@pytest.fixture()
def single_image_dir(tmp_path):
    """单图目录（规避保存自动切图 R3-14 的跨图 shapes 干扰）。"""
    from PIL import Image

    d = tmp_path / "one"
    d.mkdir()
    Image.new("RGB", (800, 600), (60, 60, 60)).save(d / "only.png")
    return d


# ================================ 本地辅助 ================================ #


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
    """打开单图文件夹并等加载完成（状态栏文件名/尺寸）。"""
    assert click_nav(win, "标注", T_NAV), "无法切换到标注页（find timeout）"
    time.sleep(1.0)
    assert click_button(win, "打开文件夹", T_NAV), "未找到'打开文件夹'按钮（find timeout）"
    assert enter_path_in_open_dialog("打开文件夹", os.environ["AVA_EDIT_IMG_DIR"], T_NAV), \
        "打开标注文件夹失败"
    deadline = time.time() + T_GENERIC
    status = ""
    while time.time() < deadline:
        try:
            status = read_status_text(win)
        except Exception:  # noqa: BLE001
            status = ""
        # open_folder 内 setCurrentRow(0)（加载首图）先于「已加载 N 张」
        # emit——filename/尺寸是毫秒级瞬态，终态口径=「已加载/张」（套件同款）
        if ("已加载" in status and "张" in status) or "only.png" in status:
            time.sleep(1.5)
            return
        time.sleep(0.4)
    pytest.fail(f"图像未加载（状态='{status}'）")


def _canvas_rect(win):
    canvas = _find_canvas(win)
    assert canvas is not None, "未定位到画布控件（find timeout）"
    return canvas.BoundingRectangle


def _abs_pt(win, rel: tuple[float, float]) -> tuple[int, int]:
    r = _canvas_rect(win)
    return (
        int(r.left + (r.right - r.left) * rel[0]),
        int(r.top + (r.bottom - r.top) * rel[1]),
    )


def _mouse(user32, x: int, y: int, down: int, up: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.08)
    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(up, 0, 0, 0, 0)


def _click_rel(win, rel: tuple[float, float]) -> None:
    """画布内相对坐标单击（单发——编辑选择不可双发：双击会触发加点）。"""
    with contextlib.suppress(Exception):
        win.SetActive()
    time.sleep(0.25)
    user32 = ctypes.windll.user32
    x, y = _abs_pt(win, rel)
    _mouse(user32, x, y, 0x0002, 0x0004)  # LEFTDOWN/LEFTUP
    time.sleep(0.4)
    logger.info("编辑单击: (%d,%d)", x, y)


def _drag_rel(win, src: tuple[float, float], dst: tuple[float, float]) -> None:
    """画布内相对坐标拖拽（press → 分步 move → release，顶点拖动原语）。

    对齐 draw_rectangle_on_canvas 的已验证输入模式：raw 拖拽前先做一次
    UIA 级画布点击（激活/焦点由 UIA 正确处理；EDIT 模式下点击三角形
    内部=重选，无副作用）——纯 ctypes press 起拖在未聚焦窗口上会被
    激活语义吃掉首个 press（W55 UIA 实测）。
    """
    import uiautomation as _ua

    fx, fy = _abs_pt(win, _INSIDE)  # 三角形内部已证安全点（0.5,0.5 恰在斜边）
    with contextlib.suppress(Exception):
        _ua.Click(fx, fy, waitTime=0.4)
    user32 = ctypes.windll.user32
    x0, y0 = _abs_pt(win, src)
    x1, y1 = _abs_pt(win, dst)
    user32.SetCursorPos(x0, y0)
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN（命中顶点→开始拖动）
    time.sleep(0.1)
    steps = 10
    for i in range(1, steps + 1):
        user32.SetCursorPos(
            int(x0 + (x1 - x0) * i / steps),
            int(y0 + (y1 - y0) * i / steps),
        )
        time.sleep(0.04)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP（拖动结束）
    time.sleep(0.5)
    logger.info("顶点拖拽: (%d,%d) -> (%d,%d)", x0, y0, x1, y1)


def _draw_triangle(win, verts: list[tuple[float, float]]) -> None:
    """Q 模式逐点单击 + 末点右键提交（不经中心聚焦点击——见用例注记）。"""
    import ctypes

    user32 = ctypes.windll.user32
    with contextlib.suppress(Exception):
        win.SetActive()
    time.sleep(0.4)
    x = y = 0
    for rel in verts:
        x, y = _abs_pt(win, rel)
        _mouse(user32, x, y, 0x0002, 0x0004)  # 左键单击加点
        time.sleep(0.15)
    time.sleep(0.15)
    _mouse(user32, x, y, 0x0008, 0x0010)      # 右键提交
    time.sleep(0.5)
    logger.info("三角形自绘完成: %s", verts)


def _shape_count(win) -> int:
    try:
        status = read_status_text(win)
    except Exception:  # noqa: BLE001
        return -1
    m = re.search(r"(\d+)\s+标注数", status)
    return int(m.group(1)) if m else -1


def _save_json(win, labels_dir: Path, name: str) -> dict:
    """保存标注 → 读回 LabelMe JSON（对话框假 True 防御：以落盘为真值，≤3 轮）。"""
    path = labels_dir / name
    dismiss_stale_dialogs()
    for attempt in range(3):
        assert click_button(win, "保存标注", T_NAV), "未找到'保存标注'按钮（find timeout）"
        if not enter_path_in_save_dialog("保存标注", str(path), timeout=8.0):
            dismiss_stale_dialogs()
            continue
        # 补键盘确认（确认点击在 #32770 内偶发丢失）
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
def test_edit_mode_drag_vertex_end_to_end(ava_app, single_image_dir, workspace_dir):
    """Q 画三角形 → 保存 before → E 拖顶点 A → 保存 after →
    JSON 对比：仅顶点 A 变化，B/C 逐点一致（拖动语义铁证）。"""
    win = ava_app
    os.environ["AVA_EDIT_IMG_DIR"] = str(single_image_dir)
    try:
        _ensure_logged_in(win)
        _wait_image_loaded(win)

        # -- 1) Q 模式画三角形（自绘：draw_polygon_on_canvas 的画布中心
        #    聚焦点击在 Q 模式会多加一个顶点——该助手为 SAM 幂等 on_press
        #    设计，PolygonLabeler 每击必加点，故此处直接单发点击）--
        assert click_button(win, "多边形", T_NAV), "未找到'多边形'按钮（find timeout）"
        _draw_triangle(win, [_V_A, _V_B, _V_C])
        deadline = time.time() + 8.0
        while time.time() < deadline and _shape_count(win) < 1:
            time.sleep(0.4)
        assert _shape_count(win) >= 1, "多边形未提交（状态栏无标注计数）"

        before = _save_json(win, workspace_dir, "edit_before.json")
        polys = [s for s in before["shapes"] if s.get("shape_type") == "polygon"]
        assert len(polys) == 1, f"期望 1 个多边形，实得 {len(polys)}"
        pts_before = polys[0]["points"]
        assert len(pts_before) == 4, (
            f"期望闭合三角形 4 点（A,B,C,A'），实得 {len(pts_before)}：{pts_before}"
        )

        # -- 2) E 模式：点内部选中 → 拖顶点 A → B/C --
        assert click_button(win, "编辑", T_NAV), "未找到'编辑'按钮（find timeout）"
        time.sleep(0.8)
        _click_rel(win, _INSIDE)        # 选中（顶点手柄渲染）
        time.sleep(0.3)
        _drag_rel(win, _V_A, _DRAG_TO)  # 拖动顶点 A
        time.sleep(0.5)

        after = _save_json(win, workspace_dir, "edit_after.json")
        polys2 = [s for s in after["shapes"] if s.get("shape_type") == "polygon"]
        assert len(polys2) == 1, f"编辑后期望 1 个多边形，实得 {len(polys2)}"
        pts_after = polys2[0]["points"]
        assert len(pts_after) == len(pts_before), (
            f"顶点数变化 {len(pts_before)} -> {len(pts_after)}（拖动不应增删点）"
        )

        def _close(p, q, tol=2.0) -> bool:
            return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol

        moved_a = not _close(pts_after[0], pts_before[0])
        b_kept = _close(pts_after[1], pts_before[1])
        c_kept = _close(pts_after[2], pts_before[2])
        assert moved_a, f"顶点 A 未移动: {pts_before[0]} -> {pts_after[0]}"
        assert b_kept, f"顶点 B 意外变化: {pts_before[1]} -> {pts_after[1]}"
        assert c_kept, f"顶点 C 意外变化: {pts_before[2]} -> {pts_after[2]}"
        logger.info(
            "编辑 E2E 铁证: A %s -> %s（B/C 保持）",
            pts_before[0], pts_after[0],
        )
    finally:
        os.environ.pop("AVA_EDIT_IMG_DIR", None)
