"""W25（FR-005）：数据管理 move 划分 + i18n 切换持久化——两条 UIA 用例。

move 划分（T2c 调查）：模式 combo 为数据页第 1 枚（[0]=划分模式/
[1]=导出格式），Select("移动") 失败时键盘回退（VK_DOWN 一步到 idx1）；
8 张 × 0.8/0.1/0.1 的 int 截断 → 划分完成态恒 "T6/V0/T2"（与洗牌
无关，确定性强断言）；move 后顶层清空 → W20 的"子目录/文件名"相对
路径分组展示（"train/xxx.bmp" 列表项），且 copy 态才有的
"已隐藏子目录图像"提示行不在场。

i18n：语言是全局持久态（user_settings.json "language" 键）——teardown
还原是硬要求：层1 UI 还原（切回中文+保存设置，保存按钮文本不随自身
保存的 retranslate 变化）+ 层2 文件级兜底（app 仅在点保存时写盘，
closeEvent 不写 → 无竞态）。残留 en_US 会让既有用例中文锚全红。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pytest

try:
    from tests.uia.uia_helpers import (
        login_admin,
        click_button,
        click_nav,
        confirm_dialog_if_present,
        enter_path_in_open_dialog,
        find_combo_controls,
        find_control_by_name,
        wait_any_status,
        wait_status,
    )
    from tests.uia.test_pole_dataset_flows import _ensure_logged_in
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (
        login_admin,  # type: ignore[no-redef]
        click_button,
        click_nav,
        confirm_dialog_if_present,
        enter_path_in_open_dialog,
        find_combo_controls,
        find_control_by_name,
        wait_any_status,
        wait_status,
    )
    from test_pole_dataset_flows import _ensure_logged_in  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

T_NAV = 20
T_IMPORT = 60
T_SPLIT = 90

# dist 树现存 known-good 快照（T2c 取证读出；层2 兜底覆写用）
_KNOWN_GOOD_SETTINGS = {
    "theme": "night",
    "language": "ch_CN",
    "device": "cuda",
    "precision": "fp32",
    "workspace": "",
    "cache_dir": "",
}


def _count_bmp(d: Path) -> int:
    return len(list(d.rglob("*.bmp")))


def _combo_select(combo, item_text: str, direction: str = "down") -> bool:
    """QComboBox 选项选择：Select 优先，键盘回退（方向感知）。

    QComboBox 的 UIA Name 为空（T2c 探针实证），只能按布局序定位；
    Select 可能抛 COM 错（0x80040201）——回退 SetFocus+方向键+回车，
    本文件场景恰为相邻项一步可达（down: idx0→idx1；up: idx1→idx0）。
    """
    try:
        combo.Select(item_text)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("combo.Select(%r) 失败（%s），键盘回退", item_text, e)
    try:
        import uiautomation as ua

        combo.SetFocus()
        time.sleep(0.2)
        key = ua.Keys.VK_UP if direction == "up" else ua.Keys.VK_DOWN
        ua.SendKey(key)
        time.sleep(0.2)
        ua.SendKey(ua.Keys.VK_RETURN)
        time.sleep(0.3)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("键盘回退也失败: %s", e)
        return False


def test_move_split_groups_subdirs(ava_app, pole_subset_dir, workspace_dir):
    """move 模式划分：顶层搬空 + 相对路径分组展示 + 确定性 T6/V0/T2。"""
    win = ava_app
    _ensure_logged_in(win)
    data_dir = workspace_dir / "data"

    # 导入（与 test_pole_import_and_split 同骨架）
    assert click_nav(win, "数据管理", T_NAV), "无法切换到数据管理页"
    time.sleep(1.0)
    assert click_button(win, "选择目录", T_NAV), "未找到'选择目录'按钮"
    assert enter_path_in_open_dialog("选择数据目录", str(data_dir), T_NAV)
    assert click_button(win, "导入图像", T_NAV)
    assert enter_path_in_open_dialog("选择导入源目录", str(pole_subset_dir), T_IMPORT)
    assert wait_status(win, "导入完成", T_IMPORT), "导入未完成"
    assert _count_bmp(data_dir) == 8, f"导入后应 8 张，实得 {_count_bmp(data_dir)}"

    # move 模式：数据页 combo[0]=划分模式（[1]=导出格式）
    combos = find_combo_controls(win, timeout=T_NAV)
    assert len(combos) >= 2, f"数据页应 ≥2 个 combo，实得 {len(combos)}"
    assert _combo_select(combos[0], "移动"), "划分模式切换到'移动'失败"
    time.sleep(0.5)

    assert click_button(win, "划分数据集", T_NAV), "未找到'划分数据集'按钮"
    confirm_dialog_if_present("确认划分", timeout=5.0)
    status = wait_status(win, "划分完成", T_SPLIT)
    assert status, "划分未完成"
    assert "T6/V0/T2" in status, f"8×0.8/0.1/0.1 应确定性 T6/V0/T2: {status!r}"

    # 磁盘铁证：顶层搬空、子目录各归其位
    assert len(list(data_dir.glob("*.bmp"))) == 0, "move 后顶层应无散图"
    assert _count_bmp(data_dir / "train") == 6
    assert _count_bmp(data_dir / "val") == 0
    assert _count_bmp(data_dir / "test") == 2

    # UIA 分组锚（ListItemControl Name=item 文本，T2c 探针实证）
    assert find_control_by_name(win, "train/", None, 10) is not None, (
        "应出现 'train/' 相对路径分组列表项（W20 分组展示）"
    )
    assert find_control_by_name(win, "test/", None, 10) is not None
    # move 态特征：copy 态才有的折叠提示行不在场
    assert find_control_by_name(win, "已隐藏子目录图像", None, 2.0) is None, (
        "顶层无图时不应出现'已隐藏子目录图像'提示行"
    )


def _settings_path() -> Path:
    src = os.environ.get("AVA_UIA_SOURCE", "exe").lower()
    if src == "python":
        return REPO_ROOT / "configs" / "user_settings.json"
    return REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal" / "configs" / "user_settings.json"


def _wait_settings_contains(token: str, timeout: float = 5.0) -> bool:
    sp = _settings_path()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sp.exists() and token in sp.read_text(encoding="utf-8"):
            return True
        time.sleep(0.3)
    return False


def test_i18n_switch_persists(ready_admin_cfg, ava_app):
    """切 English→保存→落盘 en_US→（还原）切回中文→落盘 ch_CN。"""
    win = ava_app
    login_admin(win)
    sp = _settings_path()
    try:
        assert click_nav(win, "设置", T_NAV), "无法切换到设置页"
        assert find_control_by_name(win, "系统设置", None, T_NAV) is not None
        time.sleep(0.8)

        # 设置页 combo 布局序：[0]主题 [1]语言 [2]设备（字面量项，语言无关；
        # W28 删 precision 死键后为 3 个——本断言 ≥4 系 W28 漏迁移，潜伏至
        # v5 后首次全量 UIA 才暴露，迁移留档）
        combos = find_combo_controls(win, timeout=T_NAV)
        assert len(combos) >= 3, f"设置页应 ≥3 个 combo，实得 {len(combos)}"
        lang = combos[1]
        assert _combo_select(lang, "English (US)"), "语言切换到 English 失败"

        assert click_button(win, "保存设置", T_NAV), "未找到'保存设置'按钮"
        # 保存流程先 set_language(en_US) 再 emit → 状态文案应为英文
        status = wait_any_status(win, ["Settings saved", "设置已保存", "Save"], 20)
        assert status and "Settings saved" in status, (
            f"切英文后保存状态应为 'Settings saved'，实得 {status!r}（语言未生效）"
        )
        assert _wait_settings_contains('"en_US"'), (
            f"user_settings.json 未落 en_US: {sp}"
        )

        # ---------- 层1 UI 还原 ----------
        assert _combo_select(lang, "中文 (简体)", direction="up"), "切回中文失败"
        assert click_button(win, "保存设置", 10), "还原保存失败"
        # set_language(ch_CN) 先于 emit → 恒中文锚
        assert wait_status(win, "设置已保存", 10), "还原保存未确认"
        assert _wait_settings_contains('"ch_CN"'), "user_settings.json 未还原 ch_CN"
    finally:
        # ---------- 层2 文件级兜底（app 仅保存时写盘，无竞态） ----------
        try:
            if sp.exists() and '"ch_CN"' not in sp.read_text(encoding="utf-8"):
                sp.write_text(
                    json.dumps(_KNOWN_GOOD_SETTINGS, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.warning("i18n 用例兜底覆写 user_settings.json → ch_CN")
        except OSError:
            logger.exception("i18n 兜底覆写失败")
