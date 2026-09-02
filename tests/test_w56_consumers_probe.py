"""W56-0 前置探针（RED 基线）——AnnotationMode 工业形态成员存在性。

任务链：tasks-skolpha-replication.md Task 1 步骤 3。本文件在 W56-A 实现
前必须红（证明守卫先于实现存在）；实现落地（Task 2）后转绿并长期驻留
——成员存在性探针是后续 io/工厂/页面链路的最低层哨兵。

Task 12（FB-016 守卫翻新）：增全集相等断言——枚举成员集、模板任务码集
（增量守卫生长期结束，翻为全集口径防漂移；模式模块文件清单全集由
test_dynamic_import_guard 五方一致性天然覆盖）。
"""
import pytest

from labeling.base import AnnotationMode

# W56 复刻程序全集口径（Task 12 定稿）
_EXPECTED_MODES = {
    "POLYGON", "RECTANGLE", "CUT_LINE", "OPERATION",
    "INTERACTIVE", "REGION_SAM", "EDIT",
}


@pytest.mark.unit
def test_probe_cut_line_mode_member_exists():
    """CUT_LINE（对标 SKolpha cut_line_label）枚举成员必须存在。"""
    assert hasattr(AnnotationMode, "CUT_LINE"), (
        "AnnotationMode.CUT_LINE 缺失——W56-A 切割线形态未落地"
    )


@pytest.mark.unit
def test_probe_operation_mode_member_exists():
    """OPERATION（对标 SKolpha operation_label）枚举成员必须存在。"""
    assert hasattr(AnnotationMode, "OPERATION"), (
        "AnnotationMode.OPERATION 缺失——W56-A 操作标注形态未落地"
    )


@pytest.mark.unit
def test_annotation_mode_full_set():
    """全集相等（FB-016）：七成员不多不少——增删成员须同步本断言与全链路。"""
    actual = {m.name for m in AnnotationMode}
    assert actual == _EXPECTED_MODES, (
        f"AnnotationMode 全集漂移: {sorted(actual ^ _EXPECTED_MODES)}"
    )


@pytest.mark.unit
def test_train_template_task_full_set():
    """全集相等（FB-016）：模板任务码 = 全部可训练任务（ocr 推理-only 除外）。"""
    from core.interfaces_supervised import TaskType
    from training.train_templates import REPO_TEMPLATE_DIR, load_templates

    expected = {
        t.value for t in TaskType if t is not TaskType.OCR
    }
    covered = {task for task, _variant in load_templates(REPO_TEMPLATE_DIR)}
    assert covered == expected, (
        f"模板任务码全集漂移: 缺={sorted(expected - covered)} "
        f"多={sorted(covered - expected)}"
    )
