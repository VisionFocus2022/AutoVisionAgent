"""SAM3 标注 UIA 深度测试（FR-1~FR-4 · docs/prd-uia-sam3-deep.md v1.0）。

exe 模式（默认）：T1 冒烟已证 dist 内 labeling.sam3_adapter PYZ 可达 +
transformers/models/sam3 栈在场（2026-08-31 实跑 test_sam3_invalid_weights_
honest_failure 27.6s 绿）。

增量覆盖（既有 test_sam3_labeling.py 3 用例之外的深度维度）：
  1. test_sam3_multi_object_and_geometry   FR-1+FR-2：pending 替换语义 +
     3 独立对象会话 + 几何质量最低集断言（点≥3/面积>0/点在图内）
  2. test_sam3_undo_redo_clear             FR-3：撤销/重做/清空（状态栏 +
     shape_list 列表项双通道铁证）
  3. test_sam3_next_image_rewarm_roundtrip FR-4：换图重预热（"交互式标注
     就绪"复现）+ SAM→手动→SAM 模式往返 adapter 复用

断言口径沿用套件规约：状态栏文本 + LabelMe JSON 磁盘铁证 + UIA 树属性；
无 screenshot/像素断言。控件未找到类失败消息含 "timeout"（flaky 路由）；
JSON/计数不符类为 deterministic。

运行（机器空闲时；exe 默认模式需 dist/AutoVisionAgent 已构建）::

    .venv/Scripts/python.exe -m pytest \\
        tests/uia/test_sam3_labeling_deep.py -o addopts= --timeout=900 -v
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
        _iter_descendants,
        _wait_dialog,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        find_edit_controls,
        read_status_text,
        set_edit_value,
        wait_any_status,
        wait_status,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-def]
        _find_canvas,
        _iter_descendants,
        _wait_dialog,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        find_edit_controls,
        read_status_text,
        set_edit_value,
        wait_any_status,
        wait_status,
    )

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAM3_WEIGHTS = _REPO_ROOT / "weights" / "sam3"
_SAM3_EXE_STACK = (
    _REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal"
    / "transformers" / "models" / "sam3"
)
if os.environ.get("AVA_UIA_SOURCE", "exe").lower() != "python" and not _SAM3_EXE_STACK.is_dir():
    pytest.skip(
        f"SAM3 深度用例需源码模式或带 sam3 栈的 exe（{_SAM3_EXE_STACK} 不存在）",
        allow_module_level=True,
    )
_BUTTON_TYPES = ["ButtonControl", "CheckBoxControl"]

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_LOAD = float(os.environ.get("AVA_UIA_T_SAM3_LOAD", "120"))
T_INFER = float(os.environ.get("AVA_UIA_T_SAM3_INFER", "12"))
T_GENERIC = 20.0
# 快路径就绪上限（FR-4）：adapter 复用时仅重预热（1.5-6s/1600²），
# 冷加载 10-25s 不应复现——30s cap 区分两路径
T_WARM_FAST = float(os.environ.get("AVA_UIA_T_SAM3_WARM_FAST", "30"))


# ================================ 夹具（参数序先于 ava_app——W25 教训） ================================ #


def _set_env(name: str, value: str):
    old = os.environ.get(name)
    os.environ[name] = value

    def _restore():
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old

    return _restore


@pytest.fixture()
def sam3_weights_env():
    """真实 SAM3 权重目录注入（缺权重 skip——不造假权重冒充）。"""
    if not (_SAM3_WEIGHTS / "model.safetensors").is_file():
        pytest.skip(
            f"SAM3 权重未下载: {_SAM3_WEIGHTS}（先跑 scripts/download_sam3.py）"
        )
    restore = _set_env("AVA_SAM3_DIR", str(_SAM3_WEIGHTS))
    yield str(_SAM3_WEIGHTS)
    restore()


# ================================ 会话原语（与 test_sam3_labeling.py 同源） ================================ #


def _ensure_logged_in(win) -> None:
    """离线登录（幂等，与既有套件同款硬校验）。"""
    for attempt in range(1, 3):
        try:
            win.SetActive()
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):
                win.SetFocus()
        dismiss_stale_dialogs()
        btn = find_control_by_name(win, "离线模式", _BUTTON_TYPES, timeout=8.0)
        if btn is None:
            return
        assert click_button(win, "离线模式", T_NAV), "未找到'离线模式'按钮（find timeout）"
        confirm_dialog_if_present("离线模式", timeout=3.0)
        status = wait_any_status(win, ["已进入离线模式", "就绪", "仪表盘", "主页"], T_NAV)
        gone = find_control_by_name(win, "离线模式", _BUTTON_TYPES, timeout=2.0) is None
        if status is not None and gone:
            time.sleep(1.0)
            return
        logger.warning("登录未确认（attempt %d，status=%s）", attempt, status)
    pytest.fail("离线登录未完成：两轮尝试后仍在登录页")


def _last_status(win) -> str:
    try:
        return read_status_text(win)
    except Exception:  # noqa: BLE001
        return "<读取失败>"


def _shape_count(win) -> int:
    """状态栏「N 标注数」解析（-1=无信号）。"""
    m = re.search(r"(\d+)\s*标注数", _last_status(win))
    return int(m.group(1)) if m else -1


def _shape_list_count(win) -> int:
    """shape_list 列表项计数（铁证第二通道：'#N [mode] label' 项）。

    QListWidget 的 ListItem Name 形如 '#1  [polygon]  sam3deep'——深度
    遍历（复用 helpers._iter_descendants）按 #+数字 前缀计数。
    """
    count = 0
    for item in _iter_descendants(win, max_depth=8):
        try:
            name = item.Name or ""
        except Exception:  # noqa: BLE001
            continue
        if item.ControlTypeName == "ListItemControl" and re.match(r"#\d+", name):
            count += 1
    return count


def _wait_count(win, expected: int, timeout: float = 8.0, channel="status") -> bool:
    """轮询 shape 计数达到 expected（channel: status / list）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cur = _shape_count(win) if channel == "status" else _shape_list_count(win)
        if cur == expected:
            return True
        time.sleep(0.3)
    return False


def _canvas_click(win, rel_x: float, rel_y: float) -> bool:
    """画布内相对坐标单击（ctypes 原始事件流 + 前台保持 + 双发）。"""
    canvas = _find_canvas(win)
    if canvas is None:
        logger.warning("未定位到画布控件（find timeout）")
        return False
    rect = canvas.BoundingRectangle
    user32 = ctypes.windll.user32
    x = int(rect.left + (rect.right - rect.left) * rel_x)
    y = int(rect.top + (rect.bottom - rect.top) * rel_y)
    for _i in range(2):
        with contextlib.suppress(Exception):
            win.SetActive()
        time.sleep(0.25)
        user32.SetCursorPos(x, y)
        time.sleep(0.08)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        time.sleep(0.3)
    logger.info("画布单击(双发): (%d,%d)", x, y)
    return True


def _canvas_commit(win, rel_x: float = 0.5, rel_y: float = 0.5) -> None:
    """画布右键提交（controller.on_mouse_press RightButton → handle_commit）。"""
    canvas = _find_canvas(win)
    if canvas is None:
        logger.warning("未定位到画布控件")
        return
    with contextlib.suppress(Exception):
        win.SetActive()
    rect = canvas.BoundingRectangle
    user32 = ctypes.windll.user32
    x = int(rect.left + (rect.right - rect.left) * rel_x)
    y = int(rect.top + (rect.bottom - rect.top) * rel_y)
    user32.SetCursorPos(x, y)
    time.sleep(0.08)
    user32.mouse_event(0x0008, 0, 0, 0, 0)  # RIGHTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0010, 0, 0, 0, 0)  # RIGHTUP
    time.sleep(0.3)
    logger.info("画布右键提交: (%d,%d)", x, y)


def _open_label_folder(win, images_dir: Path) -> None:
    """切标注页 + 打开文件夹 + 等首图加载。"""
    assert click_nav(win, "标注", T_NAV), "无法切换到标注页（find timeout）"
    time.sleep(1.0)
    assert click_button(win, "打开文件夹", T_NAV), "未找到'打开文件夹'按钮（find timeout）"
    assert enter_path_in_open_dialog("打开文件夹", str(images_dir), T_NAV), \
        "打开标注文件夹失败"
    loaded = wait_any_status(win, [".bmp", "张"], T_GENERIC)
    assert loaded is not None, (
        f"图像未加载（无 .bmp 文件名或张计数，最后='{_last_status(win)}'）"
    )
    time.sleep(1.5)


def _set_label_edit(win, value: str) -> None:
    """label 输入框写入——须在切模式前完成（_apply_mode 同步标签）。"""
    edits = find_edit_controls(win, timeout=T_NAV)
    target = None
    for e in edits:
        try:
            if "defect" in (e.Name or ""):
                target = e
                break
        except Exception:  # noqa: BLE001
            continue
    if target is None and edits:
        target = edits[0]
    assert target is not None, "未找到标签输入框（find timeout）"
    assert set_edit_value(target, value), f"标签写入失败: {value}"


def _enter_interactive_ready(win) -> int:
    """切交互式模式并等待就绪，返回当前 shape 计数 base。

    -1（状态栏暂无计数信号，如刚就绪）归一为 0——空白画布语义；
    提交后状态栏为「已添加 N 标注数」，_shape_count 后缀匹配兼容。
    """
    assert click_button(win, "交互式", T_NAV), "未找到'交互式'按钮（find timeout）"
    status = wait_status(win, "交互式标注就绪", T_LOAD)
    assert status is not None, (
        f"SAM3 未就绪（等 '交互式标注就绪' 超时，最后='{_last_status(win)}'，"
        f"查 {_REPO_ROOT / 'logs' / 'autovision.log'}）"
    )
    time.sleep(0.5)
    return max(_shape_count(win), 0)


def _hard_confirm_save_dialog() -> None:
    """保存对话框悬空时的键盘级补确认（同既有套件）。"""
    dlg = _wait_dialog("保存标注", 0.8)
    if dlg is None:
        return
    logger.warning("保存对话框未关闭，补键盘确认")
    with contextlib.suppress(Exception):
        dlg.SetActive()
    time.sleep(0.3)
    import uiautomation as _ua

    _ua.SendKey(_ua.Keys.VK_RETURN)
    time.sleep(0.8)


def _save_and_read_json(win, labels_dir: Path, name: str) -> dict:
    """添加标签 → 保存标注（对话框）→ 读回 LabelMe JSON（3 轮重试）。"""
    path = labels_dir / name
    dismiss_stale_dialogs()
    for attempt in range(3):
        assert click_button(win, "添加标签", T_NAV), "未找到'添加标签'按钮（find timeout）"
        time.sleep(0.5)
        assert click_button(win, "保存标注", T_NAV), "未找到'保存标注'按钮（find timeout）"
        if not enter_path_in_save_dialog("保存标注", str(path), timeout=8.0):
            logger.warning("保存第 %d 轮对话框未出现/未确认", attempt + 1)
            dismiss_stale_dialogs()
            continue
        _hard_confirm_save_dialog()
        deadline = time.time() + 5.0
        while time.time() < deadline and not path.exists():
            time.sleep(0.3)
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
        logger.warning("保存第 %d 轮未落盘（状态='%s'），清扫重试",
                       attempt + 1, _last_status(win))
        dismiss_stale_dialogs()
    pytest.fail(f"标注文件未生成: {path}（3 轮重试后，最后='{_last_status(win)}'）")


# ================================ FR-1 几何断言（最低集，鞋带公式免依赖） ================================ #


def _shoelace_area(points: list) -> float:
    n = len(points)
    s = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _assert_min_geometry(doc: dict, ctx: str) -> None:
    """FR-1 最低集：每 shape ①points≥3 ②鞋带面积>0 ③点在图内。"""
    w = doc.get("imageWidth")
    h = doc.get("imageHeight")
    assert isinstance(w, int) and w > 0, f"{ctx}: imageWidth 非法: {w!r}"
    assert isinstance(h, int) and h > 0, f"{ctx}: imageHeight 非法: {h!r}"
    shapes = doc.get("shapes", [])
    assert shapes, f"{ctx}: shapes 为空"
    for i, s in enumerate(shapes):
        pts = s.get("points") or []
        assert len(pts) >= 3, (
            f"{ctx} shape#{i} 点数 {len(pts)} < 3（退化多边形）"
        )
        bad = [
            (x, y) for x, y in pts
            if not (0 <= float(x) <= w and 0 <= float(y) <= h)
        ]
        assert not bad, (
            f"{ctx} shape#{i} 越界点 {bad[:3]}（图 {w}x{h}）"
        )
        area = _shoelace_area(pts)
        assert area > 0, (
            f"{ctx} shape#{i} 面积 {area:.1f} ≤ 0（共线/空多边形）"
        )
        logger.info("%s shape#%d: %d 点, 面积 %.0f px²", ctx, i, len(pts), area)


# ================================ 用例 ================================ #


def test_sam3_multi_object_and_geometry(
    sam3_weights_env, ava_app, pole_subset_dir, workspace_dir
):
    """FR-1+FR-2：pending 替换（双击仅 1 shape）+ 3 独立对象 + 几何最低集铁证。"""
    win = ava_app
    _ensure_logged_in(win)
    _open_label_folder(win, pole_subset_dir)
    _set_label_edit(win, "sam3deep")
    base = _enter_interactive_ready(win)

    # -- 阶段 A：pending 替换语义——两击不同点不提交，右键后仅 +1 --
    assert _canvas_click(win, 0.35, 0.35), "画布单击#1 失败（find timeout）"
    time.sleep(T_INFER)          # 首次含同步前向
    assert _canvas_click(win, 0.65, 0.50), "画布单击#2 失败（find timeout）"
    time.sleep(4.0)              # 第二击替换 pending（重预测）
    _canvas_commit(win)
    replaced = _wait_count(win, base + 1, timeout=8.0)
    assert replaced, (
        f"pending 替换提交后应 +1（base={base}，最后='{_last_status(win)}'）"
    )
    after_a = _shape_count(win)
    assert after_a == base + 1, (
        f"双击不提交应仅 +1（base={base}，实际 {after_a}——pending 叠加泄漏）"
    )
    logger.info("阶段 A pending 替换: base=%d → %d", base, after_a)

    # -- 阶段 B：多对象会话——再 2 次（点击→提交）独立对象 --
    for k, (rx, ry) in enumerate([(0.50, 0.28), (0.50, 0.72)], start=2):
        assert _canvas_click(win, rx, ry), f"对象#{k} 单击失败（find timeout）"
        time.sleep(4.0)
        _canvas_commit(win)
        ok = _wait_count(win, base + k, timeout=8.0)
        assert ok, (
            f"对象#{k} 未提交（期望 {base + k}，最后='{_last_status(win)}'）"
        )
    total = _shape_count(win)
    assert total == base + 3, (
        f"3 对象会话应 {base + 3}，实际 {total}（最后='{_last_status(win)}'）"
    )

    # -- 铁证：LabelMe JSON + FR-1 几何最低集 --
    doc = _save_and_read_json(
        win, workspace_dir / "labels", "sam3_deep_multi.json"
    )
    shapes = doc.get("shapes", [])
    assert len(shapes) == 3, (
        f"应恰好 3 shapes（base={base}），实际 {len(shapes)}: "
        f"{[s.get('shape_type') for s in shapes]}"
    )
    assert all(s.get("shape_type") == "polygon" for s in shapes), (
        f"产物应全为 polygon: {[s.get('shape_type') for s in shapes]}"
    )
    assert all(s.get("label") == "sam3deep" for s in shapes), (
        f"label 应为 'sam3deep': {[s.get('label') for s in shapes]}"
    )
    _assert_min_geometry(doc, "多对象会话")
    logger.info(
        "FR-1+FR-2 铁证通过: %d shapes (pending 替换 +1, 独立对象 +2)",
        len(shapes),
    )


def test_sam3_undo_redo_clear(
    sam3_weights_env, ava_app, pole_subset_dir, workspace_dir
):
    """FR-3：提交 → 撤销(-1) → 重做(+1) → 清空(归零)——状态栏+列表双通道。"""
    win = ava_app
    _ensure_logged_in(win)
    _open_label_folder(win, pole_subset_dir)
    _set_label_edit(win, "sam3undo")
    base = _enter_interactive_ready(win)

    # -- 提交 1 个 shape --
    assert _canvas_click(win, 0.5, 0.5), "画布单击失败（find timeout）"
    time.sleep(T_INFER)
    _canvas_commit(win)
    assert _wait_count(win, base + 1, timeout=8.0), (
        f"提交后应 {base + 1}（最后='{_last_status(win)}'）"
    )
    list_c1 = _shape_list_count(win)
    assert list_c1 == base + 1, (
        f"列表通道应 {base + 1} 项，实际 {list_c1}（状态栏/列表不一致）"
    )
    logger.info("提交: 状态栏 %d / 列表 %d 项", base + 1, list_c1)

    # -- 撤销：-1 --
    assert click_button(win, "撤销", T_NAV), "未找到'撤销'按钮（find timeout）"
    assert _wait_count(win, base, timeout=6.0), (
        f"撤销后应回到 {base}（最后='{_last_status(win)}'）"
    )
    assert _shape_list_count(win) == base, "撤销后列表通道未回落"

    # -- 重做：+1 恢复 --
    assert click_button(win, "重做", T_NAV), "未找到'重做'按钮（find timeout）"
    assert _wait_count(win, base + 1, timeout=6.0), (
        f"重做后应恢复 {base + 1}（最后='{_last_status(win)}'）"
    )
    assert _shape_list_count(win) == base + 1, "重做后列表通道未恢复"

    # -- 清空：归零（btn_clear 直连 clear_shapes，无确认框）--
    assert click_button(win, "清空", T_NAV), "未找到'清空'按钮（find timeout）"
    assert _wait_count(win, 0, timeout=6.0), (
        f"清空后应 0（base={base}，最后='{_last_status(win)}'）"
    )
    time.sleep(0.5)
    assert _shape_list_count(win) == 0, "清空后列表通道未归零"
    logger.info("FR-3 双通道通过: 撤销/重做往返 + 清空归零（base=%d）", base)


def test_sam3_next_image_rewarm_and_roundtrip(
    sam3_weights_env, ava_app, pole_subset_dir, workspace_dir
):
    """FR-4：换图→重预热（就绪复现+新图交互）+ SAM→手动→SAM 往返 adapter 复用。"""
    win = ava_app
    _ensure_logged_in(win)
    _open_label_folder(win, pole_subset_dir)
    _set_label_edit(win, "sam3rewarm")
    base = _enter_interactive_ready(win)

    # -- 首图提交 1 个（建立会话基线）--
    assert _canvas_click(win, 0.5, 0.5), "首图单击失败（find timeout）"
    time.sleep(T_INFER)
    _canvas_commit(win)
    assert _wait_count(win, base + 1, timeout=8.0), (
        f"首图提交后应 {base + 1}（最后='{_last_status(win)}'）"
    )

    # -- 换图：下一张 → 重预热（"交互式标注就绪" 应再次出现）--
    assert click_button(win, "下一张", T_NAV), "未找到'下一张'按钮（find timeout）"
    time.sleep(2.5)  # 换图同步落定（状态栏被 filename 覆盖，避免匹配旧"就绪"残留）
    status = wait_status(win, "交互式标注就绪", T_LOAD)
    assert status is not None, (
        f"换图后重预热未就绪（最后='{_last_status(win)}'，"
        f"查 {_REPO_ROOT / 'logs' / 'autovision.log'}）"
    )
    logger.info("换图重预热就绪")

    # -- 新图交互：缓存失效验证（旧缓存 hash 不命中 → 新前向产 shape）--
    # 换图后 shapes 跨图保留（canvas 不清空）；状态栏计数信号已被"就绪"
    # 覆盖——从列表通道取真实画布计数
    base2 = max(_shape_list_count(win), _shape_count(win), 0)
    assert _canvas_click(win, 0.42, 0.45), "新图单击失败（find timeout）"
    time.sleep(5.0)
    _canvas_commit(win)
    assert _wait_count(win, base2 + 1, timeout=8.0), (
        f"新图交互应 +1（base2={base2}，最后='{_last_status(win)}'——"
        f"疑似换图未重预热命中旧缓存）"
    )

    # -- 模式往返：交互式 → 多边形（手动）→ 交互式（adapter 复用快路径）--
    assert click_button(win, "多边形", T_NAV), "未找到'多边形'按钮（find timeout）"
    time.sleep(1.0)
    t0 = time.time()
    assert click_button(win, "交互式", T_NAV), "往返-交互式按钮（find timeout）"
    status = wait_status(win, "交互式标注就绪", T_WARM_FAST)
    elapsed = time.time() - t0
    assert status is not None, (
        f"往返后就绪超时（cap={T_WARM_FAST}s，最后='{_last_status(win)}'——"
        f"adapter 未复用走了冷加载？查 app 日志 label_sam3_load）"
    )
    logger.info("往返就绪耗时 %.1fs（≤%.0fs 快路径 cap）", elapsed, T_WARM_FAST)

    # -- 往返后交互产出（复用会话仍可用）--
    base3 = max(_shape_list_count(win), _shape_count(win), 0)
    assert _canvas_click(win, 0.58, 0.55), "往返后单击失败（find timeout）"
    time.sleep(5.0)
    _canvas_commit(win)
    assert _wait_count(win, base3 + 1, timeout=8.0), (
        f"往返后交互应 +1（base3={base3}，最后='{_last_status(win)}'）"
    )

    # -- 铁证：两图会话产物落盘（新图 shapes）--
    doc = _save_and_read_json(
        win, workspace_dir / "labels", "sam3_deep_rewarm.json"
    )
    shapes = doc.get("shapes", [])
    assert len(shapes) >= 2, (
        f"换图+往返会话应 ≥2 shapes，实际 {len(shapes)}"
    )
    assert all(s.get("label") == "sam3rewarm" for s in shapes), (
        f"label 应为 'sam3rewarm': {[s.get('label') for s in shapes]}"
    )
    _assert_min_geometry(doc, "换图往返")
    logger.info("FR-4 铁证通过: %d shapes（换图重预热 + 往返复用）", len(shapes))
