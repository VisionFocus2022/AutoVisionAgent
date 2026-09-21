"""W14 C6 P2-8 零样本死线诚实化（RED 先行）。

审查 v2 P2-8：load_zero_shot 全仓 0 调用、DINOv3/CLIP 实现已随 W13 config
删除，label 页零样本回退必 raise —— list_all_tasks 仍恒前置 zero_shot 条目，
serving ListTasks 原样向 gRPC/C# 客户端广告不可用能力。

本文件固化新契约：
1. list_all_tasks 不再广告 zero_shot（预留注入点，未注入即不可用）。
   （W18 / v3 P2-7 演进：零样本回退桥已整体删除；W59 起 label 页
   AI 预标注入口亦已删——"无 DET 引擎 WARNING 留痕"用例随特性移除。）
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


# ------------------------------- P2-8 任务清单诚实化 ------------------------------- #
@pytest.mark.unit
def test_list_all_tasks_no_longer_advertises_zero_shot():
    """list_all_tasks 不得再广告 zero_shot（无内置实现、0 调用方的死线）。"""
    from industrial_vision_platform.vision_dispatcher import VisionModelDispatcher

    tasks = VisionModelDispatcher.list_all_tasks()
    task_names = {t["task"] for t in tasks}
    assert "zero_shot" not in task_names, (
        f"zero_shot 仍被广告: {sorted(task_names)}"
    )
    # 有监督任务仍按注册表诚实枚举
    assert "det" in task_names


@pytest.mark.unit
def test_list_all_tasks_zero_shot_entry_absent_even_with_empty_registry(monkeypatch):
    """注册表枚举失败时也不得退回 zero_shot 广告（空清单即空清单）。"""
    import models.supervised.registry as reg_mod

    class _BoomReg:
        def list(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _BoomReg())
    # 触发惰性注册的 import 也要被掐掉，保证走 except 分支
    import industrial_vision_platform.vision_dispatcher as disp_mod

    monkeypatch.setattr(
        "models.supervised.engines.register_all_engines",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=False,
    )

    tasks = disp_mod.VisionModelDispatcher.list_all_tasks()
    assert tasks == [], f"枚举失败时仍返回了条目: {tasks}"
