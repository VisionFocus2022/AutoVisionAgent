"""W25（FR-002）：predict 推理页 UIA——核心推理页首条 UIA 覆盖。

前置（T2a 调查）：tiny_det_model_path（YAML 离线构造，.venv 内
DetYoloEngine.load→infer→eval 全链实测通过）；断言锚全部取自
gui/pages/predict/page.py 源码文案（状态栏/表行/预览占位）。

历史生产缺陷（W25 首跑擒获，W26 已修复）：exe 打包排除 matplotlib
但 ultralytics 导入链硬依赖（ultralytics/models/yolo/semantic/train.py:8
import matplotlib.pyplot）→ 打包态引擎加载必败。W26 修复：spec
excludes 去 matplotlib + PYZ 清场（pytest/pydub/web 栈）重打包，
本用例随之去 strict-xfail 转正。
"""
from __future__ import annotations

import logging
import re
import time

import pytest

try:
    from tests.uia.uia_helpers import (
        click_button,
        click_nav,
        enter_path_in_open_dialog,
        find_control_by_name,
        wait_any_status,
        wait_status,
    )
    from tests.uia.test_pole_dataset_flows import _ensure_logged_in
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        click_button,
        click_nav,
        enter_path_in_open_dialog,
        find_control_by_name,
        wait_any_status,
        wait_status,
    )
    from test_pole_dataset_flows import _ensure_logged_in  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

T_NAV = 20
T_LOAD = 60    # 首次加载 exe 内冷 import ultralytics 实测 ~5-15s，宽余量
T_INFER = 60


@pytest.mark.usefixtures("ava_app")
def test_predict_requires_model_first(ava_app):
    """负向探针（不依赖引擎加载，可绿）：未加载模型推理 → 提示先加载。"""
    win = ava_app
    _ensure_logged_in(win)

    assert click_nav(win, "推理", T_NAV), "无法切换到推理页"
    time.sleep(1.0)
    assert click_button(win, "单张推理", T_NAV), "未找到'单张推理'按钮"
    assert wait_status(win, "请先加载模型", 10), "未加载模型应提示'请先加载模型'"


@pytest.mark.usefixtures("ava_app")
def test_predict_single_image(ava_app, sample_images_dir, tiny_det_model_path):
    """单张推理全链：加载模型→选图推理→分数渲染→结果行→预览更新。

    历史：W25 因 exe 缺 matplotlib 生产缺陷以 strict xfail 锁定，
    W26 重打包修复后转正（见模块 docstring）。
    """
    win = ava_app
    _ensure_logged_in(win)

    assert click_nav(win, "推理", T_NAV), "无法切换到推理页"
    time.sleep(1.0)

    # 加载模型（弹原生文件对话框）
    assert click_button(win, "加载模型", T_NAV), "未找到'加载模型'按钮"
    assert enter_path_in_open_dialog(
        "选择模型权重", str(tiny_det_model_path), T_NAV
    ), "选择模型权重对话框失败"
    status = wait_any_status(win, ["模型已加载", "加载失败"], T_LOAD)
    assert status and "模型已加载" in status, f"模型加载未成功: {status!r}"
    assert find_control_by_name(
        win, tiny_det_model_path.name, None, 10
    ) is not None, "lbl_model 应显示权重文件名"

    # 单张推理
    assert click_button(win, "单张推理", T_NAV)
    assert enter_path_in_open_dialog(
        "选择图像", str(sample_images_dir / "img_001.png"), T_NAV
    ), "选择图像对话框失败"
    status = wait_status(win, "分数", T_INFER)
    assert status, "推理未在时限内完成（无'分数'状态）"
    assert "img_001.png" in status, status
    assert re.search(r"分数[:：]\s*\d+\.\d{3}", status), (
        f"分数渲染格式异常（应为 X.XXX 三位小数）: {status!r}"
    )
    # 随机权重对合成平图实测零检出（分数: 0.000）——不锚精确值防假绿

    # 结果表行在场（文件列单元格）
    assert find_control_by_name(win, "img_001.png", None, 10) is not None, (
        "结果表应出现 img_001.png 行"
    )

    # 预览更新：初始占位文案"选择图像进行推理"被 pixmap 替换而消失
    deadline = time.time() + 10
    while time.time() < deadline:
        if find_control_by_name(win, "选择图像进行推理", None, 1.0) is None:
            break
        time.sleep(0.5)
    else:
        pytest.fail("预览占位文案未消失（预览未更新）")
