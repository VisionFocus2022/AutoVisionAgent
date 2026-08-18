"""W14 C6 P2-8 零样本死线诚实化（RED 先行）。

审查 v2 P2-8：load_zero_shot 全仓 0 调用、DINOv3/CLIP 实现已随 W13 config
删除，label 页零样本回退必 raise —— list_all_tasks 仍恒前置 zero_shot 条目，
serving ListTasks 原样向 gRPC/C# 客户端广告不可用能力。

本文件固化新契约：
1. list_all_tasks 不再广告 zero_shot（预留注入点，未注入即不可用）；
2. label 页零样本回退失败必须以 WARNING 级日志留下真实原因（原先仅
   exception 级堆栈，且消息不含根因），便于 UI 日志排查。
   （W18 / v3 P2-7 演进：零样本回退桥已整体删除——本条改为锚定
   "无 DET 引擎 → WARNING 携带'零样本未实装'诚实原因"，见下方用例。）
"""
from __future__ import annotations

import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")
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


# ------------------------------- P2-8 label 页回退留痕 ------------------------------- #
# W18（v3 P2-7）演进：零样本 dispatcher 回退桥已删，本用例从"回退失败留痕"
# 改锚"引擎不可用留痕"——WARNING 必须携带"零样本未实装"诚实原因。
@pytest.mark.unit
def test_run_ai_prelabel_no_det_engine_warns_zero_shot_not_impl(
    tmp_path, monkeypatch, caplog
):
    """无 DET 引擎：必须有一条 WARNING 携带"零样本未实装"诚实原因。"""
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((16, 16, 3), np.uint8))
    assert ok
    img = tmp_path / "img.png"
    img.write_bytes(buf.tobytes())

    import models.supervised.registry as reg_mod

    class _NoReg:
        def has(self, t):
            return False

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _NoReg())

    # 零样本桥已删（W18）：dispatcher 若被触碰即证明回退复活
    import industrial_vision_platform.vision_dispatcher as disp_mod

    disp_calls = []
    monkeypatch.setattr(disp_mod, "get_dispatcher", lambda: disp_calls.append(1))

    from gui.pages.label.page import run_ai_prelabel

    with caplog.at_level(logging.WARNING, logger="gui.pages.label.page"):
        shapes = run_ai_prelabel(str(img))

    assert shapes == []
    assert disp_calls == [], "W18 后 run_ai_prelabel 不得再走 dispatcher"
    warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "零样本未实装" in r.getMessage()  # 诚实原因可见
    ]
    assert warns, (
        f"未捕获引擎不可用的 WARNING 记录: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
