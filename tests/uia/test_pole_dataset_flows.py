"""极柱真实数据集 + 未覆盖页的 UIA 扩展测试（wave11-arch-uia FR-004）。

被测应用：dist\\AutoVisionAgent\\AutoVisionAgent.exe（uiautomation 真窗驱动）
数据源：E:\\学习项目\\极柱外观检标注图（conftest.pole_subset_dir 抽 4 正常 + 4 缺陷）
断言通道（docs/uia-test-plan-full-coverage.md）：状态栏文本 + 磁盘产物 + UIA 树属性；
无任何 screenshot/像素断言。控件未找到类失败消息含 "timeout"（路由 flaky），
行为不符类（文件/数量/JSON 结构）为 deterministic。

用例：
  1. test_pole_import_and_split         极柱 bmp（括号文件名）导入 + 划分三目录
  2. test_pole_label_polygon_and_rectangle 多边形（右键提交）+ 矩形 + 切图 + 双 JSON 铁证
  3. test_project_create_flow           项目创建（浏览选存储目录 → 落盘 + 列表）
  4. test_settings_theme_persist        主题切换 + 保存持久化铁证
  5. test_home_dashboard                主页仪表盘渲染冒烟

运行（与既有套件同前提：桌面会话 / exe 已构建 / 无同名单实例）::

    .venv/Scripts/python.exe -m pytest tests/uia/test_pole_dataset_flows.py -o addopts= --timeout=300
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import pytest

try:
    from tests.uia.uia_helpers import (
        app_log_path,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        draw_polygon_on_canvas,
        draw_rectangle_on_canvas,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_combo_controls,
        find_control_by_name,
        find_edit_controls,
        set_edit_value,
        wait_any_status,
        wait_status,
        read_status_text,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-def]
        app_log_path,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        draw_polygon_on_canvas,
        draw_rectangle_on_canvas,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_combo_controls,
        find_control_by_name,
        find_edit_controls,
        set_edit_value,
        wait_any_status,
        wait_status,
        read_status_text,
    )

logger = logging.getLogger(__name__)

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_IMPORT = float(os.environ.get("AVA_UIA_T_IMPORT", "60"))
T_SPLIT = float(os.environ.get("AVA_UIA_T_SPLIT", "90"))
T_LABEL = float(os.environ.get("AVA_UIA_T_LABEL", "40"))
T_GENERIC = 20.0

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUTTON_TYPES = ["ButtonControl", "CheckBoxControl"]

# ================================ 公共步骤 ================================ #

def _ensure_logged_in(win) -> None:
    """离线登录（幂等）：真前台化 + 清扫残留对话框 + 登录完成硬校验。

    W11 教训：登录失败会连锁迷失——UIA 树能看到隐藏页控件，导航点击
    "成功"但页面不切，最终倒在各页 find timeout。故登录完成以
    "离线模式按钮从树中消失"为硬标准，两轮重试后仍失败则明确报错。
    """
    for attempt in range(1, 3):
        try:
            win.SetActive()
        except Exception:  # noqa: BLE001
            try:
                win.SetFocus()
            except Exception:  # noqa: BLE001
                pass
        dismiss_stale_dialogs()
        btn = find_control_by_name(win, "离线模式", _BUTTON_TYPES, timeout=8.0)
        if btn is None:
            logger.info("未探测到登录页（attempt %d，可能已登录），继续", attempt)
            return
        assert click_button(win, "离线模式", T_NAV), "未找到'离线模式'按钮（find timeout）"
        confirm_dialog_if_present("离线模式", timeout=3.0)
        status = wait_any_status(win, ["已进入离线模式", "就绪", "仪表盘", "主页"], T_NAV)
        btn_gone = find_control_by_name(win, "离线模式", _BUTTON_TYPES, timeout=2.0) is None
        if status is not None and btn_gone:
            time.sleep(1.0)
            return
        logger.warning(
            "登录未确认（attempt %d，status=%s，按钮已消失=%s），重试",
            attempt, status, btn_gone,
        )
    pytest.fail(
        f"离线登录未完成：两轮尝试后仍在登录页（最后='{_last_status(win)}'）"
    )


def _last_status(win) -> str:
    try:
        return read_status_text(win)
    except Exception:  # noqa: BLE001
        return "<读取失败>"


def _shape_count(win) -> int:
    """从状态栏解析当前图标注数（"N 标注数"）；无该信号返回 -1。

    增量检测用（draw 后计数应 > 基线），不锁死具体数值——重试累计多形状
    亦判提交成功（铁证最终以保存的 JSON 为准）。
    """
    m = re.search(r"(\d+)\s*标注数", _last_status(win))
    return int(m.group(1)) if m else -1


def _wait_count_increase(win, base: int, timeout: float = 3.0) -> bool:
    """轮询等待标注数高于 base。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shape_count(win) > base:
            return True
        time.sleep(0.3)
    return False


def _count_bmp(directory: Path) -> int:
    return len(list(directory.rglob("*.bmp")))


# ================================ 用例 ================================ #

@pytest.mark.usefixtures("ava_app")
def test_pole_import_and_split(ava_app, pole_subset_dir: Path, workspace_dir: Path):
    """极柱真实 bmp（含 "(N)" 括号文件名）导入 + 数据集划分三目录铁证。"""
    win = ava_app
    data_dir = workspace_dir / "data"
    _ensure_logged_in(win)

    assert click_nav(win, "数据管理", T_NAV), "无法切换到数据管理页（find timeout）"
    time.sleep(1.0)

    # 1) 选择目标数据目录
    assert click_button(win, "选择目录", T_NAV), "未找到'选择目录'按钮（find timeout）"
    assert enter_path_in_open_dialog("选择数据目录", str(data_dir), T_NAV), "选择目标目录失败"

    # 2) 导入极柱子集（8 张真实 bmp）
    assert click_button(win, "导入图像", T_NAV), "未找到'导入图像'按钮（find timeout）"
    assert enter_path_in_open_dialog("选择导入源目录", str(pole_subset_dir), T_NAV), \
        "选择导入源目录失败"
    status = wait_status(win, "导入完成", T_IMPORT)
    assert status is not None, (
        f"导入未完成：状态栏未出现'导入完成'（最后='{_last_status(win)}'）"
    )
    assert "0 张" not in status, f"导入张数为 0，状态: {status}"

    # 铁证 1：磁盘文件数 = 8（括号文件名真实落盘）
    n_imported = _count_bmp(data_dir)
    assert n_imported == 8, (
        f"导入后 data 目录应有 8 张 bmp，实际 {n_imported}（data={data_dir}）"
    )
    assert any(p.name.startswith("(N)") for p in data_dir.glob("*.bmp")), \
        "导入结果中未见 '(N)' 前缀文件——正常图样本丢失"

    # 3) 划分数据集（默认 0.8/0.1/0.1，确认弹窗点"是"）
    assert click_button(win, "划分数据集", T_NAV), "未找到'划分数据集'按钮（find timeout）"
    confirm_dialog_if_present("确认划分", timeout=5.0)
    status = wait_status(win, "划分完成", T_SPLIT)
    assert status is not None, (
        f"划分未完成：状态栏未出现'划分完成'（最后='{_last_status(win)}'）"
    )

    # 铁证 2：train/val/test 三子目录合计 = 8（分布随机只锁总量）
    sub_names = ["train", "val", "test"]
    sub_counts = {}
    for name in sub_names:
        sub = data_dir / name
        assert sub.is_dir(), f"划分后未创建子目录: {sub}"
        sub_counts[name] = _count_bmp(sub)
    total = sum(sub_counts.values())
    assert total == 8, (
        f"train/val/test 合计应 8 张，实际 {sub_counts}（合计 {total}，data={data_dir}）"
    )
    logger.info("极柱导入+划分完成: %s", sub_counts)


@pytest.mark.usefixtures("ava_app")
def test_pole_label_polygon_and_rectangle(ava_app, pole_subset_dir: Path, workspace_dir: Path):
    """极柱真实图：多边形（右键提交）→ 保存；切下一张 → 矩形 → 保存；双 JSON 铁证。"""
    win = ava_app
    labels_dir = workspace_dir / "labels"
    _ensure_logged_in(win)

    assert click_nav(win, "标注", T_NAV), "无法切换到标注页（find timeout）"
    time.sleep(1.0)

    # 1) 打开极柱子集文件夹，等首图加载（极柱图全为 .bmp，状态栏会显示文件名）
    assert click_button(win, "打开文件夹", T_NAV), "未找到'打开文件夹'按钮（find timeout）"
    assert enter_path_in_open_dialog("打开文件夹", str(pole_subset_dir), T_NAV), \
        "打开标注文件夹失败"
    loaded = wait_any_status(win, [".bmp", "张"], T_LABEL)
    assert loaded is not None, (
        f"图像未加载（无 .bmp 文件名或张计数，最后='{_last_status(win)}'）"
    )
    time.sleep(1.5)

    # 2) 多边形：点 4 顶点 + 右键提交（labeling/controller.py:113）
    assert click_button(win, "多边形", T_NAV), "未找到'多边形'模式按钮（find timeout）"
    time.sleep(0.5)
    base = _shape_count(win)
    poly_committed = False
    for attempt in range(2):
        draw_polygon_on_canvas(
            win, [(0.32, 0.32), (0.68, 0.32), (0.68, 0.62), (0.40, 0.70)]
        )
        if _wait_count_increase(win, base, timeout=3.0):
            poly_committed = True
            break
        logger.info("多边形尝试 %d 未提交，状态: '%s'", attempt + 1, _last_status(win))
    assert poly_committed, (
        f"多边形未提交：右键提交后标注数未增加（base={base}，最后='{_last_status(win)}'）"
    )

    assert click_button(win, "添加标签", T_NAV), "未找到'添加标签'按钮（find timeout）"
    time.sleep(0.5)
    assert click_button(win, "保存标注", T_NAV), "未找到'保存标注'按钮（find timeout）"
    polygon_path = labels_dir / "polygon.json"
    assert enter_path_in_save_dialog("保存标注", str(polygon_path), timeout=6.0), \
        "保存标注对话框未出现（多边形已提交却无保存框）"
    wait_status(win, "已保存", timeout=3.0)

    # 3) 切下一张图
    assert click_button(win, "下一张", T_NAV), "未找到'下一张'按钮（find timeout）"
    time.sleep(1.2)
    wait_status(win, "张", timeout=T_GENERIC)

    # 4) 矩形标注（拖拽）
    assert click_button(win, "矩形", T_NAV), "未找到'矩形'模式按钮（find timeout）"
    time.sleep(0.5)
    base = _shape_count(win)
    rect_committed = False
    for attempt in range(3):
        draw_rectangle_on_canvas(
            win, 0.30 + 0.05 * attempt, 0.30 + 0.05 * attempt, 0.65, 0.65
        )
        if _wait_count_increase(win, base, timeout=3.0):
            rect_committed = True
            break
        # 回退：Enter 强制 commit（controller.handle_commit）
        try:
            import uiautomation as _ua
            _ua.SendKey(_ua.Keys.VK_RETURN)
            time.sleep(0.3)
            if _shape_count(win) > base:
                rect_committed = True
                break
        except Exception:  # noqa: BLE001
            pass
        logger.info("矩形尝试 %d 未提交，状态: '%s'", attempt + 1, _last_status(win))
    assert rect_committed, (
        f"矩形未提交：拖拽后标注数未增加（base={base}，最后='{_last_status(win)}'，"
        f"查 {app_log_path()} 是否缺 labeling.modes 模块）"
    )

    assert click_button(win, "添加标签", T_NAV), "未找到'添加标签'按钮（find timeout）"
    time.sleep(0.5)
    assert click_button(win, "保存标注", T_NAV), "未找到'保存标注'按钮（find timeout）"
    rectangle_path = labels_dir / "rectangle.json"
    assert enter_path_in_save_dialog("保存标注", str(rectangle_path), timeout=6.0), \
        "保存标注对话框未出现（矩形已提交却无保存框）"
    wait_status(win, "已保存", timeout=3.0)

    # 铁证：两个 LabelMe JSON 落盘且结构/切图正确
    deadline = time.time() + 5.0
    while time.time() < deadline and not (
        polygon_path.exists() and rectangle_path.exists()
    ):
        time.sleep(0.3)
    assert polygon_path.exists() and polygon_path.stat().st_size > 0, \
        f"多边形标注文件未生成: {polygon_path}"
    assert rectangle_path.exists() and rectangle_path.stat().st_size > 0, \
        f"矩形标注文件未生成: {rectangle_path}"

    poly_doc = json.loads(polygon_path.read_text(encoding="utf-8"))
    rect_doc = json.loads(rectangle_path.read_text(encoding="utf-8"))
    assert len(poly_doc.get("shapes", [])) >= 1 and any(
        s.get("shape_type") == "polygon" for s in poly_doc["shapes"]
    ), f"polygon.json 应含 shape_type=polygon，实际: {poly_doc.get('shapes')}"
    assert len(rect_doc.get("shapes", [])) >= 1 and any(
        s.get("shape_type") == "rectangle" for s in rect_doc["shapes"]
    ), f"rectangle.json 应含 shape_type=rectangle，实际: {rect_doc.get('shapes')}"
    assert poly_doc.get("imagePath") != rect_doc.get("imagePath"), (
        f"两次保存的 imagePath 相同（{poly_doc.get('imagePath')}）——切图未生效"
    )
    assert ".bmp" in (poly_doc.get("imagePath") or ""), \
        f"imagePath 应指向 bmp 文件，实际: {poly_doc.get('imagePath')}"
    logger.info("极柱标注铁证通过: poly=%s rect=%s",
                poly_doc.get("imagePath"), rect_doc.get("imagePath"))


@pytest.mark.usefixtures("ava_app")
def test_project_create_flow(ava_app, workspace_dir: Path):
    """项目创建：改名 → 浏览选存储目录（触发 store 重初始化）→ 创建 → 落盘 + 列表铁证。"""
    win = ava_app
    proj_name = "uia_proj_w11"
    proj_root = workspace_dir / "projects"
    proj_root.mkdir(parents=True, exist_ok=True)
    _ensure_logged_in(win)

    assert click_nav(win, "项目管理", T_NAV), "无法切换到项目管理页（find timeout）"
    page_ready = find_control_by_name(win, "新建项目", None, timeout=T_NAV)
    assert page_ready is not None, "项目管理页未加载（未见'新建项目'标签，find timeout）"
    time.sleep(0.8)

    # 1) 项目名：默认 "my_project" 的 QLineEdit 改为 proj_name
    edits = find_edit_controls(win, timeout=T_NAV)
    name_edit = None
    for e in edits:
        try:
            if "my_project" in (e.Name or ""):
                name_edit = e
                break
        except Exception:  # noqa: BLE001
            continue
    if name_edit is None:
        name_edit = edits[0] if edits else None
        logger.warning("未按默认值定位名称框，回退第一个 Edit（共 %d 个）", len(edits))
    assert name_edit is not None, "未找到项目名输入框（find timeout）"
    assert set_edit_value(name_edit, proj_name), "写入项目名失败"

    # 2) 存储目录：走"浏览"（_browse_root → setText + _init_store 重初始化）
    assert click_button(win, "浏览", T_NAV), "未找到存储目录'浏览'按钮（find timeout）"
    assert enter_path_in_open_dialog("选择存储目录", str(proj_root), T_NAV), \
        "选择存储目录对话框操作失败"
    time.sleep(0.8)

    # 3) 创建
    assert click_button(win, "创建", T_NAV), "未找到'创建'按钮（find timeout）"
    status = wait_any_status(win, ["已创建", "创建成功", "创建失败"], T_GENERIC)
    assert status is not None, (
        f"创建无终态反馈（最后='{_last_status(win)}'）"
    )
    assert "失败" not in status, f"项目创建失败: {status}"

    # 铁证 1：存储目录下出现项目目录
    matches = [p for p in proj_root.glob(f"*{proj_name}*") if p.is_dir()]
    assert matches, f"项目目录未落盘: {proj_root} 下无 *{proj_name}*"

    # 铁证 2：项目列表含项目名
    listed = find_control_by_name(win, proj_name, None, timeout=T_GENERIC)
    assert listed is not None, (
        f"项目列表未见 '{proj_name}'（find timeout；磁盘已创建 {matches[0]}）"
    )
    logger.info("项目创建铁证通过: %s", matches[0])


@pytest.mark.usefixtures("ava_app")
def test_settings_theme_persist(ava_app):
    """设置页：主题切换 浅色 → 保存 → user_settings.json 持久化铁证 → 恢复深色。"""
    win = ava_app
    _ensure_logged_in(win)

    assert click_nav(win, "设置", T_NAV), "无法切换到设置页（find timeout）"
    title = find_control_by_name(win, "系统设置", None, timeout=T_NAV)
    assert title is not None, "设置页未加载（未见'系统设置'标签，find timeout）"
    time.sleep(0.8)

    combos = find_combo_controls(win, timeout=T_NAV)
    assert len(combos) >= 4, (
        f"设置页应含 ≥4 个下拉框（主题/语言/设备/精度），实际 {len(combos)}（find timeout）"
    )
    theme_combo = combos[0]  # 布局顺序：主题在最前（appear_form 第一行）

    # 1) 切浅色（UIA Selection 模式）
    selected = False
    try:
        theme_combo.Select("浅色")
        selected = True
        logger.info("已 Select('浅色')")
    except Exception as e:  # noqa: BLE001
        logger.warning("Select('浅色') 失败: %s，尝试键盘回退", e)
    if not selected:
        try:
            theme_combo.SetFocus()
            import uiautomation as _ua
            _ua.SendKey(_ua.Keys.VK_DOWN)
            time.sleep(0.2)
            _ua.SendKey(_ua.Keys.VK_RETURN)
            selected = True
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"主题下拉框无法选择'浅色'（Select 与键盘回退均失败: {e}）")
    time.sleep(0.5)

    # 2) 保存设置
    assert click_button(win, "保存设置", T_NAV), "未找到'保存设置'按钮（find timeout）"
    status = wait_any_status(win, ["已保存", "保存成功", "已写入"], T_GENERIC)
    assert status is not None, f"保存无终态反馈（最后='{_last_status(win)}'）"

    # 铁证：user_settings.json 含 theme 键（exe 模式在 _internal/configs，不污染仓库）
    src_mode = os.environ.get("AVA_UIA_SOURCE", "exe").lower()
    if src_mode == "python":
        cfg = _REPO_ROOT / "configs" / "user_settings.json"
    else:
        cfg = _REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal" / "configs" / "user_settings.json"
    deadline = time.time() + 5.0
    while time.time() < deadline and not cfg.exists():
        time.sleep(0.3)
    assert cfg.exists(), f"设置未持久化: {cfg} 不存在"
    content = cfg.read_text(encoding="utf-8", errors="ignore")
    assert "theme" in content, f"user_settings.json 无 theme 键: {cfg} → {content[:200]}"
    logger.info("主题持久化铁证通过: %s", cfg)

    # 3) 恢复深色（尽力而为，失败不判红——铁证已完成）
    try:
        theme_combo.Select("深色")
        time.sleep(0.3)
        click_button(win, "保存设置", 5.0)
        wait_status(win, "已保存", timeout=5.0)
    except Exception as e:  # noqa: BLE001
        logger.warning("恢复深色主题失败（不影响铁证）: %s", e)


@pytest.mark.usefixtures("ava_app")
def test_home_dashboard(ava_app):
    """主页仪表盘渲染冒烟：关键区块标签在 UIA 树可见。"""
    win = ava_app
    _ensure_logged_in(win)

    assert click_nav(win, "主页", T_NAV), "无法切换到主页（find timeout）"
    time.sleep(1.0)
    for label in ["仪表盘", "快捷操作", "最近项目", "检测历史"]:
        ctrl = find_control_by_name(win, label, None, timeout=T_GENERIC)
        assert ctrl is not None, (
            f"主页未见'{label}'区块标签（find timeout，主页渲染不完整）"
        )
    logger.info("主页仪表盘渲染冒烟通过")
