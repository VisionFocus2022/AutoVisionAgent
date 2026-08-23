"""AutoVisionAgent "登录 → 导入图片 → 标注 → 训练 → 部署" 全流程 UIA 自动化测试。

被测应用：dist\\AutoVisionAgent\\AutoVisionAgent.exe（PySide6 桌面应用）
测试技术：Windows UI Automation（uiautomation 库）从外部驱动真实 UI

流程步骤（每步验证状态栏反馈）：
  0. 登录页：真实 admin 登录（W39：离线模式已降 operator，全流程需
     导航 train/deploy 等 operator 不可见页；凭据由 ready_admin_cfg 预置）
     （conftest 会预创建 configs/license.key 以跳过确认对话框）
  1. 数据管理页：选择目标目录 → 导入图像（源目录）→ 等"导入完成"
  2. 标注页：打开文件夹 → 切矩形模式 → 画矩形 → 添加标签 → 保存标注 → 等"已保存"
  3. 训练页：开始训练 → 等"训练完成"（模拟训练模式，无需 GPU/真实引擎）
  4. 发布页：浏览选模型 → 选输出目录 → 导出 → 等"导出进行中..."（流程触发即通过；
     若环境有 torch+真实模型则进一步等"导出完成"）

运行::

    pytest tests/uia/test_full_workflow.py -v -s

运行前提：
  - 桌面会话（不能在无头/服务会话中运行，UIA 需桌面交互）
  - dist\\AutoVisionAgent\\AutoVisionAgent.exe 已构建
    （或设置 AVA_UIA_SOURCE=python 用源码运行，需 PySide6）
  - 无同名 AutoVisionAgent 实例正在运行
  - 可选：AVA_UIA_MODEL 指向真实 .pt 以验证完整导出
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

# 兼容 pytest 顶层模式加载（无 tests.uia 包），优先用包导入，失败则用直接导入
try:
    from tests.uia.uia_helpers import (
        app_log_path,
        click_button,
        click_login_button_precise,
        click_nav,
        confirm_dialog_if_present,
        draw_rectangle_on_canvas,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        sort_login_edits,
        wait_any_status,
        wait_status,
        _iter_descendants,
        read_status_text,
        set_edit_value,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        app_log_path,
        click_button,
        click_login_button_precise,
        click_nav,
        confirm_dialog_if_present,
        draw_rectangle_on_canvas,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        sort_login_edits,
        wait_any_status,
        wait_status,
        _iter_descendants,
        read_status_text,
        set_edit_value,
    )

logger = logging.getLogger(__name__)

# 各步骤超时（秒），可用环境变量调大以适配慢机
T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "15"))
T_IMPORT = float(os.environ.get("AVA_UIA_T_IMPORT", "30"))
T_LABEL = float(os.environ.get("AVA_UIA_T_LABEL", "30"))
T_TRAIN = float(os.environ.get("AVA_UIA_T_TRAIN", "180"))
T_DEPLOY = float(os.environ.get("AVA_UIA_T_DEPLOY", "30"))

REPO_ROOT = Path(__file__).resolve().parents[2]
_FLOW_PWD = "UiaFlow#2026"  # ≥8 字符（登录校验下限）


def _uia_config_dirs() -> list:
    """UIA 可用的应用 config 目录（python 源码模式 + exe 模式双覆盖）。"""
    return [
        REPO_ROOT / "configs",
        REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal" / "configs",
    ]


@pytest.fixture()
def ready_admin_cfg():
    """预置免改密 admin（users.json 直写，备份还原）——W39：离线模式降
    operator 后，全流程导航 train/deploy 需真实 admin 登录。

    双模式 config 目录均覆盖（python 源码/exe）；已有 users.json 先备份
    （.uia-bak），teardown 还原；无则删除预置件。参数顺序上须先于
    ava_app（users.json 需在应用启动前就位）。
    """
    import json

    from core.auth import hash_password

    h, s, iters = hash_password(_FLOW_PWD)
    db = {"admin": {
        "password_hash": h, "salt": s, "role": "admin",
        "iterations": iters, "must_change": False,
    }}
    touched: list = []
    try:
        for cfg in _uia_config_dirs():
            if not cfg.exists():
                continue
            users = cfg / "users.json"
            if users.exists():
                bak = cfg / (users.name + ".uia-bak")
                users.replace(bak)
                touched.append((bak, users))
            users.write_text(
                json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            touched.append((users, None))  # (预置文件, None)=teardown 删除
        yield
    finally:
        for path, restore_to in reversed(touched):
            try:
                if restore_to is None:
                    path.unlink(missing_ok=True)
                else:
                    path.replace(restore_to)
            except OSError:
                logger.warning("还原 %s 失败", path, exc_info=True)


# ================================ 全流程测试 ================================ #

@pytest.mark.usefixtures("ava_app")
def test_import_annotate_train_deploy(
    ready_admin_cfg,
    ava_app,
    sample_images_dir: Path,
    workspace_dir: Path,
    fake_model_path: Path,
):
    """全流程：登录 → 导入图片 → 标注 → 训练 → 部署。"""
    win = ava_app
    data_dir = workspace_dir / "data"
    labels_dir = workspace_dir / "labels"
    deploy_out = workspace_dir / "models"

    # -------- 步骤0：离线模式登录（应用默认停在登录页）--------
    _step_login(win)

    # -------- 步骤1：导入图片（数据管理页）--------
    _step_import_images(win, data_dir, sample_images_dir)

    # -------- 步骤2：标注（标注页）--------
    _step_annotate(win, data_dir, labels_dir)

    # -------- 步骤3：训练（训练页）--------
    _step_train(win)

    # -------- 步骤4：部署（发布页）--------
    _step_deploy(win, fake_model_path, deploy_out)

    logger.info("=== 全流程测试通过 ===")


# ================================ 各步骤实现 ================================ #

def _step_login(win) -> None:
    """登录页：真实 admin 登录（W39：离线模式已降 operator，全流程需
    导航 train/deploy 等 operator 不可见页；凭据由 ready_admin_cfg 预置
    免改密，避开首登强制改密弹窗）。

    登录成功的判定：状态栏"登录成功"或主页"就绪"（主页加载后可能
    覆盖登录状态）；精确点击'登录'按钮（泛匹配会命中含"登录"子串
    的复选框，W25 R3 实测踩坑）。
    """
    logger.info("--- 步骤0：admin 真实登录 ---")
    edits = sort_login_edits(win)
    assert len(edits) >= 2, f"登录页应有用户名/密码两个输入框，got {len(edits)}"
    assert set_edit_value(edits[0], "admin"), "用户名写入失败"
    assert set_edit_value(edits[1], _FLOW_PWD), "密码写入失败"
    assert click_login_button_precise(win), "未找到精确'登录'按钮"

    # 等待登录成功：状态栏"登录成功"或主页"就绪"/"仪表盘"
    status = wait_any_status(
        win, ["登录成功", "就绪", "仪表盘"], T_NAV
    )
    assert status is not None, (
        f"admin 登录未完成：状态栏未出现登录成功标志，"
        f"最后状态='{_last_status(win)}'"
    )
    logger.info("admin 登录完成: %s", status)
    # 等待主页渲染稳定
    time.sleep(1.0)


def _step_import_images(win, data_dir: Path, sample_images_dir: Path) -> None:
    """数据管理页：选目标目录 → 导入源目录图片 → 等"导入完成"。"""
    logger.info("--- 步骤1：导入图片 ---")
    assert click_nav(win, "数据管理", T_NAV), "无法切换到数据管理页"
    time.sleep(1.0)

    # 1a. 选择目标数据目录
    assert click_button(win, "选择目录", T_NAV), "未找到'选择目录'按钮"
    assert enter_path_in_open_dialog("选择数据目录", str(data_dir), T_NAV), \
        "选择目标目录失败"
    time.sleep(0.8)

    # 1b. 导入图像（选源目录）
    assert click_button(win, "导入图像", T_NAV), "未找到'导入图像'按钮"
    assert enter_path_in_open_dialog("选择导入源目录", str(sample_images_dir), T_NAV), \
        "选择导入源目录失败"

    # 等待导入完成
    status = wait_status(win, "导入完成", T_IMPORT)
    assert status is not None, (
        f"导入图片未完成：状态栏未出现'导入完成'，最后状态='{_last_status(win)}'"
    )
    # 验证导入张数 > 0
    assert "0 张" not in status, f"导入张数为 0，状态: {status}"
    logger.info("导入图片完成: %s", status)


def _step_annotate(win, data_dir: Path, labels_dir: Path) -> None:
    """标注页：打开文件夹 → 切矩形模式 → 画矩形 → 添加标签 → 保存标注。"""
    logger.info("--- 步骤2：标注 ---")
    assert click_nav(win, "标注", T_NAV), "无法切换到标注页"
    time.sleep(1.0)

    # 2a. 打开文件夹（加载 data_dir 下图片）
    assert click_button(win, "打开文件夹", T_NAV), "未找到'打开文件夹'按钮"
    assert enter_path_in_open_dialog("打开文件夹", str(data_dir), T_NAV), \
        "打开标注文件夹失败"
    # 等图像加载（状态栏出现"张"图像计数）
    loaded = wait_status(win, "张", T_NAV)
    if loaded is None:
        logger.warning("图像加载状态未确认，继续尝试: %s", _last_status(win))
    time.sleep(1.0)

    # 2b. 切换到矩形标注模式
    assert click_button(win, "矩形", T_NAV), "未找到'矩形'模式按钮"
    time.sleep(0.5)

    # 2c. 在画布上画一个矩形（可能需要多次尝试，确保 shape 被提交）
    shape_committed = False
    for attempt in range(3):
        drawn = draw_rectangle_on_canvas(
            win,
            0.30 + 0.05 * attempt,
            0.30 + 0.05 * attempt,
            0.65,
            0.65,
        )
        time.sleep(0.6)
        # 检查状态栏是否出现 "1 标注数"（_on_shapes_changed 触发）
        status = _last_status(win)
        logger.info("画矩形尝试 %d，状态: '%s'", attempt + 1, status)
        if "1" in status and "标注数" in status:
            shape_committed = True
            break
        # 回退：发送 Enter 键强制 commit（controller.handle_commit）
        try:
            import uiautomation as _ua
            _ua.SendKey(_ua.Keys.VK_RETURN)
            time.sleep(0.3)
            status = _last_status(win)
            if "1" in status and "标注数" in status:
                shape_committed = True
                logger.info("Enter 键提交成功: '%s'", status)
                break
        except Exception:  # noqa: BLE001
            pass

    if not shape_committed:
        # W4 发版检查修复：矩形未提交必须硬失败——软通过曾掩盖 exe 漏打包
        # labeling.modes.* 的缺陷（画布无响应仍"通过"全流程，era-4 假绿形态）
        raise AssertionError(
            f"矩形标注未提交：画布对鼠标拖拽无响应（最后状态='{_last_status(win)}'）。"
            "常见原因：打包缺 labeling.modes 手动模式模块（查 spec hiddenimports），"
            f"或 controller 报'标注器构造失败'（查 {app_log_path()}）"
        )

    # 2d. 应用标签（label_input 默认 "defect"）
    assert click_button(win, "添加标签", T_NAV), "未找到'添加标签'按钮"
    time.sleep(0.5)

    # 2e. 保存标注
    assert click_button(win, "保存标注", T_NAV), "未找到'保存标注'按钮"
    label_path = labels_dir / "annotation.json"
    # 保存对话框可能不弹出（若 shapes 为空则直接 emit "标注数=0"）
    # 等待对话框出现，超时则检查状态是否已显示"标注数=0"
    dlg_appeared = enter_path_in_save_dialog(
        "保存标注", str(label_path), timeout=25.0
    )
    saved = False
    if dlg_appeared:
        # save 函数发出"已保存"后会延迟 600ms 切换下一张图（覆盖状态），
        # 因此先用状态栏快速判定，再用文件存在性兜底
        status = wait_status(win, "已保存", timeout=3.0)
        if status is not None:
            logger.info("标注保存完成（状态命中）: %s", status)
            saved = True
        else:
            logger.info(
                "状态未命中'已保存'（可能被下一张图状态覆盖），改用文件验证: '%s'",
                _last_status(win),
            )
    else:
        # 对话框未弹出：可能 shapes 为空
        status = _last_status(win)
        if "标注数=0" in status or ("标注数" in status and "0" in status):
            logger.warning(
                "画布无标注，save 直接返回（标注数=0）。测试继续，但全流程不完整"
            )
        else:
            logger.info("保存对话框未出现但状态变化: '%s'", status)

    # 文件存在性兜底验证（比状态栏更可靠，避免被下一张图状态覆盖）
    if not saved and shape_committed:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if label_path.exists() and label_path.stat().st_size > 0:
                saved = True
                logger.info("标注文件已生成: %s", label_path)
                break
            time.sleep(0.3)
        if not saved:
            logger.warning(
                "未在 5s 内检测到标注文件: %s（最后状态='%s'）",
                label_path, _last_status(win),
            )

    if shape_committed:
        assert saved, (
            f"标注保存失败：状态栏未出现'已保存'且文件未生成，"
            f"最后状态='{_last_status(win)}'"
        )


def _step_train(win) -> None:
    """训练页：开始训练 → 等"训练完成"（模拟训练模式）。"""
    logger.info("--- 步骤3：训练 ---")
    assert click_nav(win, "训练", T_NAV), "无法切换到训练页"
    time.sleep(1.0)

    # 等待训练页就绪：开始训练按钮可用
    # 同时匹配 Button+CheckBox，避免 setCheckable 按钮被漏掉
    btn = find_control_by_name(
        win, "开始训练", ["ButtonControl", "CheckBoxControl"], T_NAV
    )
    assert btn is not None, "未找到'开始训练'按钮"
    btn.Click()
    logger.info("已点击'开始训练'")

    # 训练可能先出现"训练中"再"训练完成"；模拟模式失败时出现"训练失败"
    status = wait_any_status(win, ["训练完成", "训练失败"], T_TRAIN)
    assert status is not None, (
        f"训练未结束：状态栏未出现'训练完成'/'训练失败'，最后状态='{_last_status(win)}'"
    )
    assert "完成" in status, f"训练失败，状态: {status}"
    logger.info("训练完成: %s", status)


def _step_deploy(win, model_path: Path, out_dir: Path) -> None:
    """发布页：选模型 → 选输出目录 → 导出 → 等"导出进行中..."（流程触发）。

    部署页内部 torch.load 需 torch+真实模型；当前环境无 torch 时
    仅验证"导出已触发"（状态变"导出进行中..."）。若环境完整则进一步等完成。
    """
    logger.info("--- 步骤4：部署 ---")
    assert click_nav(win, "发布", T_NAV), "无法切换到发布页"
    time.sleep(1.0)

    # 4a. 浏览选择模型
    assert click_button(win, "浏览", T_NAV), "未找到模型'浏览...'按钮"
    assert enter_path_in_open_dialog("选择模型", str(model_path), T_NAV), \
        "选择模型对话框操作失败"
    time.sleep(0.8)

    # 4b. 选择输出目录（页面上第二个"浏览..."按钮）
    #   点输出目录的浏览：输出目录旁的浏览按钮。两个浏览按钮同名，依次点第二个。
    _click_second_browse(win)
    assert enter_path_in_open_dialog("选择输出目录", str(out_dir), T_NAV), \
        "选择输出目录对话框操作失败"
    time.sleep(0.8)

    # 4c. 导出
    assert click_button(win, "导出", T_NAV), "未找到'导出'按钮"

    # 等待导出流程触发的可观察证据（W35 修：不再赌"导出进行中"瞬时态——
    # 假权重下 worker 毫秒级失败即覆盖该状态，高负载轮询易错过；改为接受
    # 触发链路的任一可区分状态：进行中 / 部署失败（假权重预期终态，
    # 证明已走到 torch.load）/ 导出完成（真权重环境））
    triggered = wait_any_status(
        win, ["导出进行中", "部署失败", "导出完成"], T_DEPLOY
    )
    assert triggered is not None, (
        f"部署未触发：状态栏无任何导出链路状态，最后='{_last_status(win)}'"
    )
    logger.info("部署流程已触发: %s", triggered)

    # 若环境完整（有 torch+真实模型），进一步等待导出完成/失败
    final = wait_any_status(win, ["导出完成", "导出失败"], timeout=30.0)
    if final:
        logger.info("部署终态: %s", final)
        # 不对终态强断言：无 torch 环境"导出失败"属预期
    else:
        logger.info("部署未在 30s 内进入终态（无 torch 环境属预期，流程触发已验证）")


def _click_second_browse(win) -> None:
    """点击发布页第二个"浏览..."按钮（输出目录选择）。

    发布页有模型路径与输出目录两个"浏览..."按钮，Name 相同。点第二个。
    同时匹配 Button/CheckBox 前缀，兼容 setCheckable 按钮的 UIA 暴露。
    """
    browses = []
    for c in _iter_descendants(win, max_depth=8):
        try:
            tn = type(c).__name__
            if (tn.startswith("Button") or tn.startswith("CheckBox")) \
                    and "浏览" in (c.Name or ""):
                browses.append(c)
        except Exception:  # noqa: BLE001
            continue
    if len(browses) >= 2:
        browses[1].Click()
        logger.info("已点击第二个'浏览...'（输出目录）")
    else:
        # 回退：点找到的第一个（若只有一个，可能模型路径已自动填）
        if browses:
            browses[0].Click()
            logger.warning("仅找到一个'浏览...'按钮，已点击")
        else:
            logger.error("未找到任何'浏览...'按钮")


def _last_status(win) -> str:
    """读取当前状态栏文本（诊断用）。"""
    try:
        return read_status_text(win)
    except Exception:  # noqa: BLE001
        return "<读取失败>"
