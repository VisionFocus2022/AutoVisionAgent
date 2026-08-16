"""UIA 操作辅助函数。

封装 uiautomation 库的常用操作，针对 AutoVisionAgent（PySide6）桌面应用：
- 找主窗口 / 侧边栏导航 / 按钮 / 状态文本
- 操作原生文件对话框（打开目录 / 保存文件）
- 在标注画布上鼠标拖拽绘制矩形

设计原则：所有查找均带超时 + 重试 + 诊断输出，因为 Qt 控件 UIA 暴露
偶有延迟；文件对话框控件结构因 Windows 版本而异，采用多策略回退。
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import uiautomation as ua

logger = logging.getLogger(__name__)

# 主窗口标题（gui/main.py:81 MainWindow("AutoVisionAgent")）
MAIN_WINDOW_TITLE = "AutoVisionAgent"


# ================================ 主窗口 ================================ #

def find_main_window(timeout: float = 30.0) -> ua.WindowControl:
    """等待 AutoVisionAgent 主窗口出现并返回其控件。

    PySide6 无边框窗口仍会被 UIA 识别为 WindowControl，Name = 窗口标题。
    """
    deadline = time.time() + timeout
    last_err: Optional[Exception] = None
    while time.time() < deadline:
        try:
            win = ua.WindowControl(searchDepth=1, Name=MAIN_WINDOW_TITLE)
            if win.Exists(0.5):
                # 等待窗口可交互
                win.SetFocus()
                return win
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.5)
    raise TimeoutError(
        f"等待主窗口 '{MAIN_WINDOW_TITLE}' 超时（{timeout}s）"
        + (f"，最后错误: {last_err}" if last_err else "")
    )


# ================================ 通用查找 ================================ #

def _iter_descendants(control, max_depth: int = 6):
    """广度优先遍历控件子树（限制深度，避免过慢）。"""
    queue = [(control, 0)]
    while queue:
        cur, depth = queue.pop(0)
        if depth > max_depth:
            continue
        children = cur.GetChildren()
        for ch in children:
            yield ch
            queue.append((ch, depth + 1))


def find_control_by_name(
    root,
    name_contains: str,
    control_type=None,
    timeout: float = 10.0,
    depth: int = 8,
) -> Optional[object]:
    """在 root 子树中查找 Name 包含 name_contains 的控件。

    Args:
        control_type: 可选控件类型过滤。可为字符串（如 "ButtonControl"）、
            字符串列表（如 ["ButtonControl","CheckBoxControl"]）或 None（不限）。
            注意：PySide6 中 setCheckable(True) 的 QPushButton 会被 UIA 暴露为
            CheckBoxControl，故查找按钮时通常需同时匹配 Button + CheckBox。
        depth: 遍历最大深度。
    """
    # 归一化类型过滤为前缀列表（如 ["Button","CheckBox"]）
    type_prefixes: Optional[list[str]] = None
    if control_type:
        raw = [control_type] if isinstance(control_type, str) else list(control_type)
        type_prefixes = [t.replace("Control", "") for t in raw]

    name_lower = name_contains.lower()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for c in _iter_descendants(root, max_depth=depth):
                try:
                    cname = (c.Name or "")
                except Exception:  # noqa: BLE001
                    continue
                if name_lower and name_lower not in cname.lower():
                    continue
                if type_prefixes:
                    tn = type(c).__name__
                    if not any(tn.startswith(p) for p in type_prefixes):
                        continue
                return c
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return None


# PySide6 按钮在 UIA 中可能暴露的控件类型集合：
# - 普通 QPushButton -> ButtonControl
# - setCheckable(True) 的 QPushButton -> CheckBoxControl（侧边栏导航即此情况）
_BUTTON_TYPES = ["ButtonControl", "CheckBoxControl"]


def click_button(root, text_contains: str, timeout: float = 10.0) -> bool:
    """查找并点击文本包含 text_contains 的按钮（如"导入图像"/"开始训练"/"导出"）。

    PySide6 QPushButton 的 text 暴露为 UIA Name。
    同时匹配 ButtonControl 与 CheckBoxControl，因为 setCheckable(True)
    的按钮会被 UIA 暴露为 CheckBoxControl。
    返回是否成功点击。
    """
    btn = find_control_by_name(root, text_contains, _BUTTON_TYPES, timeout)
    if btn is None:
        logger.warning("未找到按钮: '%s'", text_contains)
        return False
    try:
        btn.SetFocus()
    except Exception:  # noqa: BLE001
        pass
    btn.Click()
    logger.info("已点击按钮: '%s'", text_contains)
    return True


def click_nav(win, page_title: str, timeout: float = 10.0) -> bool:
    """点击侧边栏导航按钮（如"数据管理"/"标注"/"训练"/"发布"）。

    侧边栏按钮文本带两个前导空格（gui/core/shell.py:168 `f"  {title}"`），
    用子串匹配规避。导航按钮均 setCheckable(True)，会被 UIA 暴露为
    CheckBoxControl，故通过 click_button 同时匹配 Button+CheckBox。
    """
    return click_button(win, page_title, timeout)


# ================================ 状态判定 ================================ #

def read_status_text(win) -> str:
    """读取主窗口状态栏文本（statusText + statusAccent 两个 QLabel 合并）。

    状态栏由两个水平排列的 QLabel 组成：
      - statusText（左）：状态主文本，如"已保存"/"就绪"/"导入完成"
      - statusAccent（右）：辅助文本，如"1 标注数"/"3 张"

    两者 bottom 相同，按 left 排序拼接，确保主文本在前。
    遍历子树找底部同一行的所有文本控件。
    """
    candidates: list[tuple[int, int, str]] = []  # (bottom, left, name)
    try:
        for c in _iter_descendants(win, max_depth=6):
            try:
                name = c.Name or ""
            except Exception:  # noqa: BLE001
                continue
            if not name:
                continue
            # 仅看文本类控件（Qt QLabel 多映射为 TextControl / EditControl）
            tn = type(c).__name__
            if not (tn.startswith("Text") or tn.startswith("Edit") or tn.startswith("Static")):
                continue
            try:
                rect = c.BoundingRectangle
            except Exception:  # noqa: BLE001
                rect = None
            if rect is None:
                continue
            candidates.append((rect.bottom, rect.left, name))
    except Exception:  # noqa: BLE001
        return ""
    if not candidates:
        return ""
    # 取最靠近底部的行（状态栏在窗口最下方）
    max_bottom = max(b for b, _, _ in candidates)
    # 容差 8px 视为同一行（避免抗锯齿/亚像素差异）
    same_row = [(l, n) for b, l, n in candidates if b >= max_bottom - 8]
    # 按 left 升序排序拼接（statusText 在左，statusAccent 在右）
    same_row.sort(key=lambda x: x[0])
    return " ".join(n for _, n in same_row)


def wait_status(
    win,
    expected_contains: str,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> Optional[str]:
    """轮询状态栏，直到文本包含 expected_contains 或超时。

    返回命中时的状态文本；超时返回 None。
    """
    expected_lower = expected_contains.lower()
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = read_status_text(win)
        if expected_lower in last.lower():
            logger.info("状态命中 '%s'：'%s'", expected_contains, last)
            return last
        time.sleep(poll_interval)
    logger.warning("等待状态 '%s' 超时，最后状态: '%s'", expected_contains, last)
    return None


def wait_any_status(
    win,
    expected_list: list[str],
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> Optional[str]:
    """轮询状态栏，命中列表中任一文本即返回。"""
    lowers = [s.lower() for s in expected_list]
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = read_status_text(win)
        last_lower = last.lower()
        for i, low in enumerate(lowers):
            if low in last_lower:
                logger.info("状态命中 '%s'：'%s'", expected_list[i], last)
                return last
        time.sleep(poll_interval)
    logger.warning("等待状态 %s 超时，最后: '%s'", expected_list, last)
    return None


# ============================ 文件对话框操作 ============================ #

def _wait_dialog(title_contains: str, timeout: float = 10.0) -> Optional[object]:
    """等待标题包含 title_contains 的对话框窗口出现。

    多策略查找：
      1. 顶层窗口（searchDepth=1）：Qt 自身弹出的非模态对话框
      2. 主窗口的子窗口（searchDepth=2）：QFileDialog 在 Windows 上使用原生
         IFileDialog（class=#32770），会作为父窗口的子窗口出现而非顶层窗口
      3. 兜底：遍历所有顶层窗口的直接子窗口，匹配 Name 或 Class=#32770
    """
    deadline = time.time() + timeout
    title_lower = title_contains.lower()
    while time.time() < deadline:
        # 策略1：顶层窗口
        try:
            dlg = ua.WindowControl(searchDepth=1, SubName=title_contains)
            if dlg.Exists(0.5):
                return dlg
        except Exception:  # noqa: BLE001
            pass

        # 策略2：顶层窗口的直接子窗口（QFileDialog 作为 modal child）
        try:
            root = ua.GetRootControl()
            for top in root.GetChildren():
                try:
                    for ch in top.GetChildren():
                        tn = type(ch).__name__
                        if not tn.startswith("Window") and not tn.startswith("Pane"):
                            continue
                        cname = (ch.Name or "")
                        ccls = ch.ClassName or ""
                        if title_lower in cname.lower() or ccls == "#32770":
                            return ch
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass

        time.sleep(0.4)
    return None


def confirm_dialog_if_present(
    title_contains: str,
    yes_texts: Optional[list[str]] = None,
    timeout: float = 3.0,
) -> bool:
    """若存在标题包含 title_contains 的 QMessageBox/对话框，点击"是/Yes"。

    用于处理"离线模式"等场景下可能弹出的确认对话框。
    返回是否发现并确认了对话框。
    """
    if yes_texts is None:
        # 兼容中英文 Qt 按钮（Qt 加载 zh_CN 翻译时为"是"，否则为 "&Yes"/"Yes"）
        yes_texts = ["是", "Yes", "&Yes", "确定", "OK", "&OK"]

    dlg = _wait_dialog(title_contains, timeout=timeout)
    if dlg is None:
        return False
    try:
        dlg.SetFocus()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.3)

    # 在对话框子树中找"是/Yes"按钮
    for c in _iter_descendants(dlg, max_depth=5):
        try:
            tn = type(c).__name__
            if not (tn.startswith("Button") or tn.startswith("CheckBox")):
                continue
            cname = (c.Name or "").strip()
            for yt in yes_texts:
                if yt in cname:
                    c.Click()
                    logger.info("对话框 '%s' 已点击确认按钮: '%s'", title_contains, cname)
                    return True
        except Exception:  # noqa: BLE001
            continue

    # 回退：直接对对话框发回车（默认按钮通常接受 Enter）
    try:
        dlg.SetFocus()
        time.sleep(0.1)
        ua.SendKey(ua.Keys.VK_RETURN)
        logger.info("对话框 '%s' 已发回车确认", title_contains)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("对话框 '%s' 确认失败: %s", title_contains, e)
        return False


def enter_path_in_open_dialog(
    dialog_title: str,
    path: str,
    timeout: float = 10.0,
) -> bool:
    """在"打开/选择目录"对话框中输入路径并确认。

    多策略兼容 Win10/Win11 原生 IFileDialog（class=#32770）：
      - 文件夹选择器：EditControl Name='文件夹:' AutoId='1152'
        + ButtonControl Name='选择文件夹' 确认
      - 文件选择器：EditControl Name='文件名:' + 回车确认
    """
    dlg = _wait_dialog(dialog_title, timeout)
    if dlg is None:
        logger.error("未等到对话框: '%s'", dialog_title)
        return False
    try:
        dlg.SetFocus()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.4)

    # 反斜杠转正斜杠，避免 SendKeys 把 \ 当转义符吃掉
    safe_path = path.replace("\\", "/")

    edited = False
    # 策略1：找"文件夹"/"文件名"编辑框（Name 含对应关键词）
    #   Win10/11 文件夹选择器为 EditControl Name='文件夹:' AutoId='1152'
    #   文件选择器为 EditControl Name='文件名:'
    for edit in _iter_descendants(dlg, max_depth=5):
        try:
            tn = type(edit).__name__
            if not tn.startswith("Edit"):
                continue
            ename = (edit.Name or "")
            auto_id = ""
            try:
                auto_id = edit.AutomationId or ""
            except Exception:  # noqa: BLE001
                pass
            # 命中条件：名称含"文件夹"/"文件名"，或 AutoId 为 1152（Win10 文件夹框）
            match = (
                "文件夹" in ename
                or "文件名" in ename
                or auto_id == "1152"
            )
            if not match:
                continue
            try:
                edit.SetFocus()
                time.sleep(0.1)
            except Exception:  # noqa: BLE001
                pass
            try:
                edit.GetValuePattern().SetValue(path)
                edited = True
                logger.info("已通过 ValuePattern 写入路径到 '%s'", ename or auto_id)
                break
            except Exception:  # noqa: BLE001
                try:
                    # 清空已有内容再输入
                    edit.SendKeys("{Ctrl}a{Delete}", waitTime=0.05)
                    edit.SendKeys(safe_path, waitTime=0.1)
                    edited = True
                    logger.info("已通过 SendKeys 写入路径到 '%s'", ename or auto_id)
                    break
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            continue

    # 策略2：回退到地址栏（Ctrl+L 聚焦地址栏 → 输入路径 → 回车）
    if not edited:
        try:
            dlg.SetFocus()
            time.sleep(0.2)
            ua.SendKeys("{Ctrl}l", waitTime=0.3)
            ua.SendKeys(safe_path, waitTime=0.2)
            edited = True
            logger.info("已通过地址栏(Ctrl+L)写入路径")
        except Exception:  # noqa: BLE001
            logger.warning("地址栏输入路径失败")

    # 策略3：直接对对话框键盘输入路径
    if not edited:
        try:
            dlg.SetFocus()
            time.sleep(0.2)
            ua.SendKeys(safe_path)
            edited = True
        except Exception:  # noqa: BLE001
            logger.warning("键盘输入路径失败")

    if not edited:
        logger.error("无法向对话框 '%s' 输入路径", dialog_title)
        return False

    time.sleep(0.3)
    # 确认：优先点击"选择文件夹"/"打开"/"确定"按钮，回退到回车
    confirmed = _click_confirm_button(dlg)
    if not confirmed:
        try:
            ua.SendKey(ua.Keys.VK_RETURN)
            confirmed = True
        except Exception:  # noqa: BLE001
            pass

    if confirmed:
        logger.info("对话框 '%s' 已输入路径并确认: %s", dialog_title, path)
        return True
    return False


def _click_confirm_button(dlg) -> bool:
    """点击对话框中的"选择文件夹"/"打开"/"保存"/"确定"按钮。"""
    confirm_texts = [
        "选择文件夹", "选择", "打开", "保存", "确定",
        "OK", "Open", "Select", "Save", "&Save",
    ]
    for c in _iter_descendants(dlg, max_depth=5):
        try:
            tn = type(c).__name__
            if not (tn.startswith("Button") or tn.startswith("CheckBox")):
                continue
            cname = (c.Name or "").strip()
            if not cname:
                continue
            for t in confirm_texts:
                if t in cname:
                    c.Click()
                    logger.info("已点击确认按钮: '%s'", cname)
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def enter_path_in_save_dialog(
    dialog_title: str,
    file_path: str,
    timeout: float = 10.0,
) -> bool:
    """在"保存"对话框中输入完整文件路径并确认。

    与打开对话框类似，文件名框接受完整路径。
    """
    return enter_path_in_open_dialog(dialog_title, file_path, timeout)


# ============================ 标注画布绘制 ============================ #

def draw_rectangle_on_canvas(
    win,
    rel_x1: float = 0.30,
    rel_y1: float = 0.30,
    rel_x2: float = 0.60,
    rel_y2: float = 0.60,
) -> bool:
    """在标注画布区域鼠标拖拽绘制矩形。

    定位画布：优先找子树中面积最大的 Pane/Custom 控件（QGraphicsView）；
    找不到则回退到主窗口工作区中央。

    坐标用相对比例（0~1）描述矩形在画布内的位置，避免硬编码像素。

    关键点：Qt QGraphicsView 需要先获得焦点才能正确接收鼠标事件，
    故先点击画布中心聚焦，再进行拖拽绘制。
    使用 ctypes 直接发送 mouse_event，确保 Qt 接收到原始鼠标事件流。
    """
    import ctypes

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004

    canvas = _find_canvas(win)
    if canvas is None:
        logger.warning("未定位到画布控件，回退到窗口中央区域绘制")
        try:
            rect = win.BoundingRectangle
        except Exception:  # noqa: BLE001
            return False
    else:
        rect = canvas.BoundingRectangle
    logger.info("画布 Rect=(%d,%d,%d,%d)", rect.left, rect.top, rect.right, rect.bottom)

    x1 = int(rect.left + (rect.right - rect.left) * rel_x1)
    y1 = int(rect.top + (rect.bottom - rect.top) * rel_y1)
    x2 = int(rect.left + (rect.right - rect.left) * rel_x2)
    y2 = int(rect.top + (rect.bottom - rect.top) * rel_y2)

    # 先点击画布中心，确保 QGraphicsView 获得焦点
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2
    try:
        ua.Click(cx, cy, waitTime=0.3)
    except Exception:  # noqa: BLE001
        pass

    logger.info("画矩形: (%d,%d) -> (%d,%d)", x1, y1, x2, y2)
    try:
        # 使用 ctypes 直接发送 mouse_event，确保 Qt 接收完整事件流：
        # press @start → move 分步 → release @end
        user32 = ctypes.windll.user32

        # 移动到起点并按下
        user32.SetCursorPos(x1, y1)
        time.sleep(0.15)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)

        # 分步移动（Qt 画布需要 mouseMoveEvent 流来实时更新预览）
        steps = 12
        for i in range(1, steps + 1):
            mx = int(x1 + (x2 - x1) * i / steps)
            my = int(y1 + (y2 - y1) * i / steps)
            user32.SetCursorPos(mx, my)
            time.sleep(0.04)

        time.sleep(0.1)
        # 释放鼠标 → 触发 mouseReleaseEvent → 提交 shape
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.3)
        logger.info("ctypes 鼠标拖拽完成")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("绘制矩形失败: %s", e)
        return False


def _find_canvas(win):
    """在窗口子树中找标注画布（QGraphicsView 的 viewport）。

    QGraphicsView 在 UIA 中多映射为 Pane/Custom 控件。为避免误选整个页面
    容器（含工具栏 + 侧边栏），筛选条件：
      1. 控件类型为 Pane/Custom
      2. 控件面积 > 200x200（排除小控件）
      3. 控件面积 < 窗口面积的 80%（排除页面容器/中央 widget）
      4. 控件 top > 窗口 top + 80（排除工具栏区域）
    选满足条件的面积最大者。
    """
    try:
        win_rect = win.BoundingRectangle
        win_area = max(1, (win_rect.right - win_rect.left)) * \
            max(1, (win_rect.bottom - win_rect.top))
        win_top = win_rect.top
    except Exception:  # noqa: BLE001
        return None

    best = None
    best_area = 0
    try:
        for c in _iter_descendants(win, max_depth=8):
            try:
                tn = type(c).__name__
                if not (tn.startswith("Pane") or tn.startswith("Custom")):
                    continue
                rect = c.BoundingRectangle
                w = max(0, rect.right - rect.left)
                h = max(0, rect.bottom - rect.top)
                if w < 200 or h < 200:
                    continue
                area = w * h
                # 排除页面容器（面积接近窗口面积）
                if area > win_area * 0.8:
                    continue
                # 排除工具栏区域（top 太靠上）
                if rect.top < win_top + 80:
                    continue
                if area > best_area:
                    best_area = area
                    best = c
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return None
    return best


__all__ = [
    "MAIN_WINDOW_TITLE",
    "find_main_window",
    "find_control_by_name",
    "click_button",
    "click_nav",
    "read_status_text",
    "wait_status",
    "wait_any_status",
    "confirm_dialog_if_present",
    "enter_path_in_open_dialog",
    "enter_path_in_save_dialog",
    "draw_rectangle_on_canvas",
]
