"""SAM3 标注 UIA 真窗测试（W46·B · prd-uia-sam-labeling.md）。

被测链路：AVA_SAM3_DIR 环境变量装配（绕开 #32770 权重对话框）→
SAM 模式按钮 → 异步加载状态栏 → 画布交互产多边形 → LabelMe JSON 铁证。

模式：**仅源码模式**（AVA_UIA_SOURCE=python）——exe 未打包
transformers/Sam3Adapter（重打包波次后放开）；权重缺失自动 skip
（scripts/download_sam3.py 可补）。

断言口径（沿用套件规约）：状态栏文本 + 磁盘 JSON 铁证 + UIA 树属性；
无 screenshot/像素断言。控件未找到类失败消息含英文 "timeout"（flaky
路由）；JSON/状态不符类为 deterministic。

用例：
  1. test_sam3_two_modes_polygon_flow  交互式/SAM 区域一图流
  （原「SAM 笔刷」「SAM 全图」用例随 2026-09-01 模式裁剪移除）
  3. test_sam3_invalid_weights_honest    伪权重目录 → 「SAM 加载失败」诚实路径

运行（机器空闲时）::

    AVA_UIA_SOURCE=python .venv/Scripts/python.exe -m pytest \\
        tests/uia/test_sam3_labeling.py -o addopts= --timeout=600 -v
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
        draw_rectangle_on_canvas,
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
        _wait_dialog,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        draw_rectangle_on_canvas,
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
# W46·B 遗留 3：exe 是否带 SAM3 栈按产物探测（transformers hook 全量
# 收集，_internal/transformers/models/sam3 在即支持；labeling.sam3_adapter
# 经 spec hiddenimports 入 PYZ——若缺，T3 用例会以「SAM3 模块不可用」
# 状态失败，即重打包缺失的明确信号）
_SAM3_EXE_STACK = (
    _REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal"
    / "transformers" / "models" / "sam3"
)
if os.environ.get("AVA_UIA_SOURCE", "exe").lower() != "python" and not _SAM3_EXE_STACK.is_dir():
    pytest.skip(
        "SAM3 UIA 用例需源码模式或带 sam3 栈的 exe"
        f"（{_SAM3_EXE_STACK} 不存在）",
        allow_module_level=True,
    )
_BUTTON_TYPES = ["ButtonControl", "CheckBoxControl"]

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_LOAD = float(os.environ.get("AVA_UIA_T_SAM3_LOAD", "120"))   # 冷加载实测 9.8-23s，取宽
T_INFER = float(os.environ.get("AVA_UIA_T_SAM3_INFER", "12"))  # 单次交互 1.5-6s（1600² 全图 PCS）
T_GENERIC = 20.0


# ================================ 夹具（参数序先于 ava_app——W25 实例化序教训） ================================ #


def _set_env(name: str, value: str):
    """写入子进程可见环境并返回恢复闭锁（python 源码分支继承 pytest env）。"""
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


@pytest.fixture()
def sam3_fake_env(tmp_path):
    """伪权重目录注入（config.json + 垃圾 safetensors——resolve 接受、加载必败）。"""
    d = tmp_path / "fake_sam3"
    d.mkdir()
    (d / "config.json").write_text("{}", encoding="utf-8")
    (d / "model.safetensors").write_bytes(b"NOT_A_SAFE_TENSOR")
    restore = _set_env("AVA_SAM3_DIR", str(d))
    yield str(d)
    restore()


# ================================ 本地辅助 ================================ #


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
    """状态栏「N 标注数」解析（-1=无信号，增量检测用）。"""
    m = re.search(r"(\d+)\s*标注数", _last_status(win))
    return int(m.group(1)) if m else -1


def _wait_count_increase(win, base: int, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shape_count(win) > base:
            return True
        time.sleep(0.3)
    return False


def _canvas_click(win, rel_x: float, rel_y: float) -> bool:
    """画布内相对坐标单击（ctypes 原始事件流 + 前台保持）。

    点击前强制 SetActive——就绪等待可长达 20s+，期间活跃用户可能把
    前台切走，raw 点击按屏幕坐标投递会落到别的窗口（W46·B 四连红
    归因；W22 ⑦ 输入争抢族）。不做预聚焦点击——Qt 鼠标事件按光标下
    控件投递无需焦点，且 SAM 模式下多一次点击=多一次同步前向冻结。
    """
    canvas = _find_canvas(win)
    if canvas is None:
        logger.warning("未定位到画布控件（find timeout）")
        return False
    rect = canvas.BoundingRectangle
    user32 = ctypes.windll.user32
    x = int(rect.left + (rect.right - rect.left) * rel_x)
    y = int(rect.top + (rect.bottom - rect.top) * rel_y)
    # 双发提高投递率（实测偶发丢失）：on_press/run 均幂等重入——
    # INTERACTIVE 重预测替换 pending、AUTO 重跑替换队列，无副作用
    for _i in range(2):
        with contextlib.suppress(Exception):
            win.SetActive()
        time.sleep(0.25)  # SetActive 异步落定（z 序/焦点切换有延迟）
        user32.SetCursorPos(x, y)
        time.sleep(0.08)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        time.sleep(0.3)
    logger.info("画布单击(双发): (%d,%d)", x, y)
    return True


def _canvas_commit(win, rel_x: float = 0.5, rel_y: float = 0.5) -> None:
    """画布右键提交（controller.on_mouse_press RightButton → handle_commit）。

    不用 SendKey(VK_RETURN)：键盘 Return 要过焦点链——此前 _set_label_edit
    对 QLineEdit 的 SetFocus 会让输入框吃掉回车（QShortcut 不触发）；
    右键提交焦点无关，pole 套件多边形用例的原生提交原语。
    """
    canvas = _find_canvas(win)
    if canvas is None:
        logger.warning("未定位到画布控件，回退 SendKey Return")
        _press_return(win)
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


def _press_return(win) -> None:
    """页面作用域 Return → controller.handle_commit（提交/drain 队列）。"""
    with contextlib.suppress(Exception):
        win.SetActive()
    import uiautomation as _ua

    _ua.SendKey(_ua.Keys.VK_RETURN)
    time.sleep(0.3)


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
    """label 输入框（QLineEdit 默认值 'defect'）写入——须在切模式前完成
    （_apply_mode → _apply_label 同步标签后创建标注器）。"""
    edits = find_edit_controls(win, timeout=T_NAV)
    target = None
    for e in edits:
        try:
            if (e.Name or "") == "defect" or "defect" in (e.Name or ""):
                target = e
                break
        except Exception:  # noqa: BLE001
            continue
    if target is None and edits:
        target = edits[0]
    assert target is not None, "未找到标签输入框（find timeout）"
    assert set_edit_value(target, value), f"标签写入失败: {value}"


def _hard_confirm_save_dialog() -> None:
    """保存对话框悬空时的键盘级补确认（W46·B 实测：确认按钮点击在
    #32770 内偶发丢失，对话框未关→app 收空路径静默返回）。

    探测对话框仍在 → SetActive + 文件名框内 VK_RETURN（=保存）。
    """
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
    """添加标签 → 保存标注（对话框）→ 读回 LabelMe JSON。

    对话框确认存在假 True 系（确认点击未落上仍返 True，W46·B 实测）——
    以文件落盘为真值；未落盘则清扫残留 #32770 后整段重试（≤3 轮）。
    """
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


# ================================ 用例 ================================ #


def test_sam3_two_modes_polygon_flow(
    sam3_weights_env, ava_app, pole_subset_dir, workspace_dir
):
    """交互式点击 / SAM 区域（拖矩形+区域内点击）→ 两多边形 JSON 铁证。"""
    win = ava_app
    _ensure_logged_in(win)
    _open_label_folder(win, pole_subset_dir)
    _set_label_edit(win, "sam3")

    # -- 1) 交互式：点击 → pending → Return 提交 --
    assert click_button(win, "交互式", T_NAV), "未找到'交互式'按钮（find timeout）"
    status = wait_status(win, "交互式标注就绪", T_LOAD)
    assert status is not None, (
        f"SAM3 未就绪（等 '交互式标注就绪' 超时，最后='{_last_status(win)}'）"
    )
    base = _shape_count(win)
    committed = 0
    for attempt in range(2):
        assert _canvas_click(win, 0.5, 0.5), "画布单击失败（find timeout）"
        time.sleep(T_INFER if attempt == 0 else 4.0)  # 首次含同步前向（UI 冻结属预期）
        _canvas_commit(win)
        if _wait_count_increase(win, base, timeout=6.0):
            committed = _shape_count(win) - base
            break
        logger.info("交互式尝试 %d 未提交，状态: '%s'", attempt + 1, _last_status(win))
    assert committed >= 1, (
        f"交互式点击未产出多边形（base={base}，最后='{_last_status(win)}'，"
        f"查 {_REPO_ROOT / 'logs' / 'autovision.log'}）"
    )

    # -- 2) SAM 区域：拖矩形设区域 → 区域内点击 → Return 提交 --
    assert click_button(win, "SAM 区域", T_NAV), "未找到'SAM 区域'按钮（find timeout）"
    time.sleep(1.0)
    base = _shape_count(win)
    for attempt in range(2):
        draw_rectangle_on_canvas(win, 0.35, 0.35, 0.75, 0.75)  # 拖=设区域（无前向）
        time.sleep(0.5)
        assert _canvas_click(win, 0.55, 0.55), "区域内单击失败（find timeout）"
        time.sleep(4.0)
        _canvas_commit(win)
        if _wait_count_increase(win, base, timeout=6.0):
            break
        logger.info("SAM 区域尝试 %d 未提交，状态: '%s'", attempt + 1, _last_status(win))
    else:
        pytest.fail(f"SAM 区域分割未产出多边形（base={base}，最后='{_last_status(win)}'）")

    # -- 铁证：两种模式的多边形落盘 --
    doc = _save_and_read_json(win, workspace_dir / "labels", "sam3_modes.json")
    shapes = doc.get("shapes", [])
    assert len(shapes) >= 2, (
        f"两模式合计应 ≥2 shapes，实际 {len(shapes)}: {[s.get('shape_type') for s in shapes]}"
    )
    assert all(s.get("shape_type") == "polygon" for s in shapes), (
        f"SAM 模式产物应全为 polygon: {[s.get('shape_type') for s in shapes]}"
    )
    assert all(s.get("label") == "sam3" for s in shapes), (
        f"label 应为 'sam3': {[s.get('label') for s in shapes]}"
    )
    assert (doc.get("imagePath") or "").endswith(".bmp"), \
        f"imagePath 应指向极柱 bmp，实际: {doc.get('imagePath')}"
    logger.info("SAM3 两模式铁证通过: %d polygons, imagePath=%s",
                len(shapes), doc.get("imagePath"))


def test_sam3_invalid_weights_honest_failure(sam3_fake_env, ava_app, pole_subset_dir):
    """伪权重目录：加载必败 → 状态栏「SAM 加载失败」+ 主窗口存活（诚实降级不崩溃）。"""
    win = ava_app
    _ensure_logged_in(win)
    _open_label_folder(win, pole_subset_dir)

    assert click_button(win, "交互式", T_NAV), "未找到'交互式'按钮（find timeout）"
    status = wait_status(win, "SAM 加载失败", 30.0)
    assert status is not None, (
        f"伪权重应触发 'SAM 加载失败'（最后='{_last_status(win)}'，"
        f"env={sam3_fake_env}）"
    )
    # 主窗口仍存活（失败不上抛崩溃、无残留模态框阻塞）
    assert win.Exists(2, 1), "SAM 加载失败后主窗口不应消失"
    logger.info("SAM3 伪权重诚实失败路径通过: '%s'", status)
