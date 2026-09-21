"""极柱工程案例全链 UIA 测试（W58 · PRD FR-2/FR-3）。

用软件生成完整工程案例：admin 登录 → 数据管理导入极柱真实 bmp →
标注页 SAM3 异步标注（W55/ADR 0003 真窗首验）+ 手动矩形 → LabelMe 保存 →
数据管理导出训练集(YOLO-seg) → 训练页真 ultralytics 训练（PRD FR-1 通道，
epochs=2）→ 推理页加载训练产物批量推理 → 导出 CSV。

断言铁证三级（无像素断言）：
  ① 状态栏终态（wait_status/wait_any_status）
  ② 磁盘产物（LabelMe JSON / yolo 目录 data.yaml / best.pt & seg_final.pt /
     batchPredict_* JSON / CSV）
  ③ UIA 树控件存在性

运行（python 源码模式，桌面会话）::

    AVA_UIA_SOURCE=python .venv/Scripts/python -m pytest \\
        tests/uia/test_pole_engineering_case.py -v -s -o addopts=

前提：桌面会话；ultralytics 已装；yolov8n-seg.pt 已缓存（跑批前预热一次
`from ultralytics import YOLO; YOLO("yolov8n-seg.pt")` 免首跑下载）。
"""
from __future__ import annotations

import contextlib
import glob
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
        click_canvas_at,
        click_canvas_right,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        draw_rectangle_on_canvas,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        login_admin,
        read_status_text,
        select_combo_item_by_text,
        set_spinner_value,
        wait_any_status,
        wait_status,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore
        app_log_path,
        click_button,
        click_canvas_at,
        click_canvas_right,
        click_nav,
        confirm_dialog_if_present,
        dismiss_stale_dialogs,
        draw_rectangle_on_canvas,
        enter_path_in_open_dialog,
        enter_path_in_save_dialog,
        find_control_by_name,
        login_admin,
        read_status_text,
        select_combo_item_by_text,
        set_spinner_value,
        wait_any_status,
        wait_status,
    )

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SAM3_WEIGHTS = REPO_ROOT / "weights" / "sam3"

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_IMPORT = 60.0
T_LABEL = 60.0
T_SAM3_LOAD = float(os.environ.get("AVA_UIA_T_SAM3", "180"))
T_TRAIN = float(os.environ.get("AVA_UIA_T_TRAIN", "900"))
T_INFER = 300.0


def _nav_ready(win, nav: str, sentinel: str, tries: int = 3) -> bool:
    """导航到页并**只探测**哨兵控件存在（不点击——配置前误触按钮会以
    默认参数启动任务，W58 实证：误点'开始训练'跑了 100 轮模拟）。"""
    for i in range(tries):
        dismiss_stale_dialogs(timeout=1.5)
        if not click_nav(win, nav, T_NAV):
            continue
        time.sleep(1.2)
        if find_control_by_name(
            win, sentinel, ["ButtonControl", "CheckBoxControl"], T_NAV
        ) is not None:
            return True
        logger.warning("第 %d 次未见哨兵 %r（重试）", i + 1, sentinel)
    return False


def _nav_click(win, nav: str, button: str, tries: int = 3) -> bool:
    """导航到页并点击按钮——UIA 树随会话变长偶发失稳（W11 形态），
    残留对话框清扫 + 导航重试加固。"""
    import uiautomation as _ua

    for i in range(tries):
        dismiss_stale_dialogs(timeout=1.5)
        if not click_nav(win, nav, T_NAV):
            continue
        time.sleep(1.2)
        if click_button(win, button, T_NAV):
            return True
        logger.warning("第 %d 次未找到 %r（重导航重试）", i + 1, button)
        with contextlib.suppress(Exception):
            _ua.SendKey(_ua.Keys.VK_ESCAPE)
    return False


def _last_status(win) -> str:
    try:
        return read_status_text(win)
    except Exception:  # noqa: BLE001
        return "<读取失败>"


def _count_status_shapes(status: str) -> int:
    m = re.search(r"(\d+)\s*标注数", status)
    return int(m.group(1)) if m else -1


# ================================ 全链主用例 ================================ #


@pytest.fixture
def sam3_real_env():
    """SAM3 真权重装配 env——**须先于 ava_app 实例化**（签名序）。

    env 跨进程边界：应用是独立子进程，只在启动时继承父进程 environ——
    测试体内再设 os.environ 应用侧读不到（W53 套件同款夹具先序约定）。
    """
    if not (SAM3_WEIGHTS / "model.safetensors").is_file():
        pytest.skip(
            f"SAM3 真权重缺失: {SAM3_WEIGHTS}（工程案例 SAM 段为真权重口径）"
        )
    old = os.environ.get("AVA_SAM3_DIR")
    os.environ["AVA_SAM3_DIR"] = str(SAM3_WEIGHTS)
    yield str(SAM3_WEIGHTS)
    if old is None:
        os.environ.pop("AVA_SAM3_DIR", None)
    else:
        os.environ["AVA_SAM3_DIR"] = old


def test_pole_engineering_case_full_chain(
    ready_admin_cfg,
    sam3_real_env,
    ava_app,
    pole_subset_dir: Path,
    workspace_dir: Path,
):
    """工程案例全链：导入→SAM3+手动标注→导出训练集→真训练→批量推理→CSV。"""
    win = ava_app
    data_dir = workspace_dir / "data"
    export_root = workspace_dir / "export"
    csv_path = workspace_dir / "predict_results.csv"

    # -------- 步骤0：admin 登录 --------
    login_admin(win)

    # -------- 步骤1：导入极柱真实 bmp --------
    _step_import(win, data_dir, pole_subset_dir)

    # -------- 步骤2：SAM3 异步标注 + 手动矩形 + LabelMe 保存 --------
    label_json = _step_annotate(win, data_dir)

    # -------- 步骤3：导出训练集（YOLO-seg） --------
    data_yaml = _step_export_dataset(win, data_dir, export_root)

    # -------- 步骤4：真训练（ultralytics，epochs=2） --------
    final_pt = _step_train(win, data_yaml)

    # -------- 步骤5：批量推理 + CSV 导出 --------
    _step_predict_and_export(win, data_dir, final_pt, csv_path)

    # -------- 终局铁证汇总 --------
    assert label_json.exists() and label_json.stat().st_size > 0
    assert data_yaml.exists()
    assert final_pt.exists() and final_pt.stat().st_size > 1024 * 1024
    assert csv_path.exists() and csv_path.stat().st_size > 0
    logger.info("=== 极柱工程案例全链通过 ===")


# ================================ 各步骤实现 ================================ #


def _step_import(win, data_dir: Path, src_dir: Path) -> None:
    """数据管理：选目录 → 导入极柱子集 → 磁盘 bmp 计数铁证。"""
    logger.info("--- 步骤1：导入极柱真实 bmp ---")
    data_dir.mkdir(parents=True, exist_ok=True)
    assert click_nav(win, "数据管理", T_NAV)
    time.sleep(1.0)
    assert click_button(win, "选择目录", T_NAV)
    assert enter_path_in_open_dialog("选择数据目录", str(data_dir), T_NAV)
    time.sleep(0.8)
    assert click_button(win, "导入图像", T_NAV)
    assert enter_path_in_open_dialog("选择导入源目录", str(src_dir), T_NAV)
    status = wait_status(win, "导入完成", T_IMPORT)
    assert status is not None and "0 张" not in status, f"导入失败: {status!r}"
    bmps = list(data_dir.rglob("*.bmp"))
    assert len(bmps) >= 4, f"磁盘铁证：导入后 bmp 应 ≥4，实得 {len(bmps)}"
    logger.info("导入完成: %s（磁盘 %d bmp）", status, len(bmps))


def _step_annotate(win, data_dir: Path) -> Path:
    """标注：SAM3 异步标注×3（W55 首验）+ 手动矩形 → 保存 LabelMe JSON。"""
    logger.info("--- 步骤2：SAM3 + 手动标注 ---")
    assert click_nav(win, "标注", T_NAV)
    time.sleep(1.0)
    assert click_button(win, "打开文件夹", T_NAV)
    assert enter_path_in_open_dialog("打开文件夹", str(data_dir), T_NAV)
    time.sleep(2.0)

    # ---- SAM3 交互式：加载 → 就绪 → 点击×3（每次：异步推理→右键提交）----
    assert click_button(win, "交互式", T_NAV), "未找到'交互式'模式按钮"
    ready = wait_any_status(
        win, ["交互式标注就绪", "SAM 加载失败"], T_SAM3_LOAD
    )
    assert ready is not None and "就绪" in ready, f"SAM3 未就绪: {ready!r}"

    sam3_clicks = 0
    for i, (fx, fy) in enumerate(((0.4, 0.4), (0.55, 0.45), (0.45, 0.6))):
        expect = 1 + i
        assert click_canvas_at(win, fx, fy), f"SAM3 点击 {i + 1} 失败"
        # W55 异步（ADR 0003）：推理中 → 回投预览 → 右键提交 → 标注数
        wait_status(win, "推理中", timeout=10.0)  # 受理即可（旧机可瞬时）
        deadline = time.time() + 30.0
        committed = False
        while time.time() < deadline:
            time.sleep(1.0)
            click_canvas_right(win, fx, fy)  # 提交 pending 多边形
            time.sleep(0.5)
            n = _count_status_shapes(_last_status(win))
            if n >= expect:
                committed = True
                break
        assert committed, (
            f"SAM3 点击 {i + 1} 未提交形状（异步回投后右键 commit 失败），"
            f"最后状态='{_last_status(win)}'（查 {app_log_path()}）"
        )
        sam3_clicks += 1
    logger.info("SAM3 异步标注提交 %d 例（W55 真窗首验通过）", sam3_clicks)

    # ---- 手动矩形一枚（工具面广度）----
    assert click_button(win, "矩形", T_NAV)
    time.sleep(0.5)
    draw_rectangle_on_canvas(win, 0.25, 0.25, 0.70, 0.70)
    deadline = time.time() + 10.0
    while time.time() < deadline and _count_status_shapes(_last_status(win)) < 4:
        time.sleep(0.5)
    try:
        import uiautomation as _ua

        _ua.SendKey(_ua.Keys.VK_RETURN)  # 强制 commit 兜底
        time.sleep(0.5)
    except Exception:  # noqa: BLE001
        pass

    # ---- 标签 + 保存 LabelMe（同名约定：图像同目录同主干 .json——
    # 导出器 labelme_dir_to_yolo 按 json∩images 配对，存别处=0 标注）----
    assert click_button(win, "添加标签", T_NAV)
    time.sleep(0.5)
    assert click_button(win, "保存标注", T_NAV)
    first_img = sorted(data_dir.glob("*.bmp"))[0]
    label_path = data_dir / f"{first_img.stem}.json"
    assert enter_path_in_save_dialog("保存标注", str(label_path), timeout=25.0)
    wait_status(win, "已保存", timeout=10.0)  # W55 已知时序：可被自动切图覆盖
    deadline = time.time() + 10.0
    while time.time() < deadline and not label_path.exists():
        time.sleep(0.3)
    assert label_path.exists(), "LabelMe JSON 未落盘"
    doc = json.loads(label_path.read_text(encoding="utf-8"))
    assert doc.get("shapes"), "LabelMe JSON 无 shapes"
    kinds = {s.get("shape_type") for s in doc["shapes"]}
    assert "polygon" in kinds, f"SAM3 多边形缺失: {kinds}"
    logger.info("标注铁证: %d shapes, 类型 %s", len(doc["shapes"]), kinds)
    return label_path


def _step_export_dataset(win, data_dir: Path, export_root: Path) -> Path:
    """数据管理：导出训练集（YOLO，默认格式）→ data.yaml 铁证。"""
    logger.info("--- 步骤3：导出训练集 ---")
    export_root.mkdir(parents=True, exist_ok=True)  # 文件夹对话框需已存在路径
    assert _nav_click(win, "数据管理", "导出训练集"), "未找到'导出训练集'"
    assert enter_path_in_open_dialog(
        "选择导出输出目录", str(export_root), T_NAV
    )
    status = wait_any_status(
        win, ["张", "失败", "请先选择目录", "无标注"], T_IMPORT
    )
    assert status is not None and "标注数" in status, (
        f"导出未完成: {status!r}（最后='{_last_status(win)}'，查 {app_log_path()}）"
    )
    yolo_dir = export_root / "yolo"
    data_yaml = yolo_dir / "data.yaml"
    assert data_yaml.exists(), f"data.yaml 未落盘: {yolo_dir}"
    labels = list((yolo_dir / "labels").rglob("*.txt")) if (yolo_dir / "labels").is_dir() else []
    assert labels, "YOLO labels 目录无 .txt"
    sample = labels[0].read_text(encoding="utf-8").strip().splitlines()
    assert sample and len(sample[0].split()) >= 8, (
        f"seg 多边形行格式异常（应 cls x1 y1 x2 y2...≥7 值）: {sample[:1]}"
    )
    logger.info("导出训练集铁证: %s（%d 标签文件）", status, len(labels))
    return data_yaml


def _step_train(win, data_yaml: Path) -> Path:
    """训练页：分割任务 + data.yaml + epochs=2 → 真 ultralytics 训练。"""
    logger.info("--- 步骤4：真训练（ultralytics）---")
    assert _nav_ready(win, "训练", "开始训练"), "训练页哨兵未就绪"
    dismiss_stale_dialogs(timeout=1.5)
    time.sleep(0.8)

    assert select_combo_item_by_text(win, "分割", combo_name_contains="任务"), (
        "任务下拉未选中'分割'"
    )
    time.sleep(0.5)

    # 数据集选择（训练页唯一'浏览'按钮 → data.yaml）
    assert click_button(win, "浏览", T_NAV), "未找到数据集'浏览'"
    assert enter_path_in_open_dialog("选择数据集", str(data_yaml), T_NAV)
    time.sleep(0.8)

    # 轮数 100 → 2（epochs spin 为首个 Spinner，当前值签名 100）
    assert set_spinner_value(win, 2, expect_current=100, index=0), (
        "轮数 Spinner 设值失败（签名/索引不符——查 Spinner 树序）"
    )

    # 表单回读铁证（W58 排障内联证据：定位配置链断点）
    from uia_helpers import find_combo_controls, find_edit_controls
    for e in find_edit_controls(win, 3):
        try:
            logger.info("表单回读 edit[%r]=%r", e.Name, e.GetValuePattern().Value)
        except Exception:  # noqa: BLE001
            logger.info("表单回读 edit[%r]=<无值>", e.Name)
    for c in find_combo_controls(win, 3):
        logger.info("表单回读 combo[%r]", c.Name)

    btn = find_control_by_name(win, "开始训练", ["ButtonControl", "CheckBoxControl"], T_NAV)
    assert btn is not None
    btn.Click()

    # 模拟回退短窗探测（真训练须无此警告——AC-2）
    early = wait_any_status(
        win, ["未选择数据集", "引擎不支持逐轮训练", "任务引擎未注册"], 6.0
    )
    assert early is None, f"误入模拟回退: {early!r}（配置链断裂，查上方表单回读）"

    final = wait_any_status(win, ["训练完成", "训练失败"], T_TRAIN)
    assert final is not None, f"训练未终态: {_last_status(win)}"
    assert "完成" in final, f"训练失败: {final}"

    outputs = Path(os.environ.get("AVA_TRAIN_OUTPUTS", str(REPO_ROOT / "outputs")))
    final_pt = outputs / "seg_final.pt"
    # W58 铁证主锚：seg_final.pt（训练器正名产物，= best.pt 拷贝）。
    # ultralytics best 原始位随版本/cwd 漂移（相对 project 嵌套 runs/ 怪癖），
    # 绝对化后应稳定在 outputs/train/weights/——glob 双兜底仅记档不判死
    assert final_pt.exists() and final_pt.stat().st_size > 1024 * 1024, (
        f"训练器最终权重未落盘/空壳: {final_pt}（真权重约 6.8MB）"
    )
    bests = sorted(REPO_ROOT.glob("outputs/train/weights/best.pt"))
    bests += sorted(REPO_ROOT.glob("runs/*/outputs/train/weights/best.pt"))
    logger.info(
        "真训练铁证: seg_final=%dMB, best 原始位=%s",
        final_pt.stat().st_size // 1048576,
        bests[-1] if bests else "<已清理（会话临时）>",
    )
    return final_pt


def _step_predict_and_export(win, data_dir: Path, model_pt: Path, csv_path: Path) -> None:
    """推理页：加载训练产物 → 批量推理 → 导出 CSV。"""
    logger.info("--- 步骤5：批量推理 + CSV ---")
    assert _nav_ready(win, "推理", "加载模型"), "推理页哨兵未就绪"
    # 推理页任务下拉选'分割'（默认 det 用 det 引擎加载 seg 权重 → task=det
    # 空结果——引擎与权重的任务须对齐；且须在点'加载模型'之前选定）
    assert select_combo_item_by_text(win, "分割", combo_name_contains="任务"), (
        "推理页任务下拉未选中'分割'"
    )
    time.sleep(0.5)
    assert click_button(win, "加载模型", T_NAV)
    assert enter_path_in_open_dialog("选择模型权重", str(model_pt), T_NAV)
    status = wait_any_status(win, ["模型已加载", "加载失败"], T_INFER)
    assert status is not None and "已加载" in status, f"模型加载失败: {status!r}"

    assert click_button(win, "批量推理", T_NAV)
    assert enter_path_in_open_dialog("选择批量推理目录", str(data_dir), T_NAV)
    done = wait_any_status(win, ["完成", "失败", "取消"], T_INFER)
    assert done is not None and "完成" in done, f"批量推理未完成: {done!r}"

    # 结果目录挂 {项目根 or workspace 根}/results（resolve_base_root 单源；
    # 本流程未设项目根 → 默认 ~/AutoVisionAgent_Projects）——与 App 同源解析
    from project.paths import resolve_base_root
    roots = [Path(resolve_base_root()), REPO_ROOT]
    dirs = sorted(
        (d for r in roots for d in glob.glob(str(r / "results" / "batchPredict_*"))),
        key=lambda d: os.path.getmtime(d),
    )
    assert dirs, "未找到任何 batchPredict_* 结果目录（两根均无）"
    latest = Path(dirs[-1])
    records = json.loads(
        (latest / "batch_results.json").read_text(encoding="utf-8")
    )
    assert isinstance(records, list) and len(records) >= 4, (
        f"批量推理记录不足: "
        f"{len(records) if isinstance(records, list) else '非数组'}"
        f"（{latest / 'batch_results.json'}）"
    )
    assert all(r.get("file") for r in records), "记录缺 file 字段"
    logger.info(
        "批量推理铁证: %d 条记录 @ %s（task=%s）",
        len(records), latest.name, records[0].get("task"),
    )

    # R3-11：批量完成自动弹'统计报表'模态框——挡后续点击，先显式关掉
    confirm_dialog_if_present("统计报表", timeout=8.0)
    dismiss_stale_dialogs(timeout=3.0)

    assert click_button(win, "导出CSV", T_NAV)
    assert enter_path_in_save_dialog("导出CSV", str(csv_path), timeout=25.0)
    deadline = time.time() + 10.0
    while time.time() < deadline and not csv_path.exists():
        time.sleep(0.3)
    assert csv_path.exists(), "CSV 未落盘"
    head = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(head) >= 2 and head[0].startswith("file"), f"CSV 内容异常: {head[:1]}"
    logger.info("CSV 铁证: %d 行", len(head))
