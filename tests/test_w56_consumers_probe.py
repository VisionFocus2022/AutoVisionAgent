"""W56-0 前置探针（RED 基线）——AnnotationMode 工业形态成员存在性。

任务链：tasks-skolpha-replication.md Task 1 步骤 3。本文件在 W56-A 实现
前必须红（证明守卫先于实现存在）；实现落地（Task 2）后转绿并长期驻留
——成员存在性探针是后续 io/工厂/页面链路的最低层哨兵。
"""
import pytest

from labeling.base import AnnotationMode


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
