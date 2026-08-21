"""W27（W26 计划）：label 页规模收敛抽取的行为保持守卫。

背景：gui/pages/label/page.py W24 实测 828 行（棘轮 850，≤800 规范上限）。
W27 把两块低内聚于"页面装配"的代码抽出（行为保持、槽名/模块级绑定不变）：
  1. gui/pages/label/workers.py —— det_engine_available + run_ai_prelabel
     （Qt-free 纯工作函数，仿 data_manage/workers.py 模式；W28 预标注
     诚实化修复将落在此模块）
  2. gui/pages/label/sam_session.py —— SAM 会话五方法 Mixin
     （_ensure_sam/_sam_warmed/_warm_sam/_sam_attach/_sam_failed 原名
     混入：invoke_main 槽名派发与 ui_on_error 经 MRO 解析不变）

兼容性红线（既有测试依赖，抽取不得破坏）：
  - tests/test_gui_label_page.py 等大量用例 monkeypatch
    gui.pages.label.page.run_ai_prelabel / det_engine_available
    —— page.py 必须保留模块级 from-import 绑定（闭包经模块全局名
    查找，补丁继续生效）
  - tests/test_sam_adapter.py TestSamDeviceWiring 源码守卫
    （adapter.load 须走 resolve_device）随代码迁移改指 sam_session.py，
    断言本体不变
"""
import ast
import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL_DIR = REPO_ROOT / "gui" / "pages" / "label"
WORKERS = LABEL_DIR / "workers.py"
SAM_SESSION = LABEL_DIR / "sam_session.py"
PAGE = LABEL_DIR / "page.py"


@pytest.mark.unit
def test_workers_module_exists_and_qt_free():
    """workers.py 在场且零 Qt 依赖（纯函数层，可同步单测）。"""
    assert WORKERS.is_file(), "gui/pages/label/workers.py 应存在（W27 抽取）"
    tree = ast.parse(WORKERS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("PySide6") for a in node.names), (
                f"workers.py 不得 import Qt（纯函数层）: {[a.name for a in node.names]}"
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("PySide6"), (
                f"workers.py 不得 from-import Qt: {node.module}"
            )


@pytest.mark.unit
def test_workers_exposes_prelabel_functions():
    """workers.py 提供 det_engine_available + run_ai_prelabel 两个顶层函数。"""
    assert WORKERS.is_file()
    tree = ast.parse(WORKERS.read_text(encoding="utf-8"))
    funcs = {
        n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"det_engine_available", "run_ai_prelabel"} <= funcs


@pytest.mark.unit
def test_page_keeps_module_level_bindings_for_monkeypatch():
    """page.py 保留模块级绑定（既有 monkeypatch 兼容红线）。

    tests/test_gui_label_page.py::test_* 与 test_gui_jobs_migration.py
    直接 setattr(gui.pages.label.page, "run_ai_prelabel"/"det_engine_available")。
    """
    src = PAGE.read_text(encoding="utf-8")
    assert "from gui.pages.label.workers import" in src or (
        "from .workers import" in src
    ), "page.py 须以模块级 import 绑定 workers 函数（monkeypatch 兼容）"


@pytest.mark.unit
def test_sam_session_mixin_provides_slot_methods():
    """SamSessionMixin 以原方法名提供 SAM 会话五方法（invoke_main 槽名
    派发按字符串找 self 上的方法——名字漂移即运行期静默断链）。"""
    assert SAM_SESSION.is_file(), "gui/pages/label/sam_session.py 应存在（W27 抽取）"
    mod = importlib.import_module("gui.pages.label.sam_session")
    mixin = getattr(mod, "SamSessionMixin", None)
    assert mixin is not None, "sam_session.py 应导出 SamSessionMixin"
    for name in ("_ensure_sam", "_sam_warmed", "_warm_sam", "_sam_attach", "_sam_failed"):
        assert callable(getattr(mixin, name, None)), (
            f"SamSessionMixin 缺方法 {name}——invoke_main 槽名派发将断链"
        )


@pytest.mark.unit
def test_label_page_inherits_mixin():
    """LabelPage 经 MRO 获得 SAM 会话方法（行为保持的混入形态）。"""
    from gui.pages.label.page import LabelPage
    from gui.pages.label.sam_session import SamSessionMixin

    assert issubclass(LabelPage, SamSessionMixin), (
        "LabelPage 应混入 SamSessionMixin（W27 抽取形态）"
    )


@pytest.mark.unit
def test_label_page_host_contract_state_init():
    """宿主契约守卫（W27 双审折入）：LabelPage 构造后四个 SAM 会话态
    属性必须在场——_ensure_sam/_warm_sam 首行直读，缺一即 AttributeError。
    """
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    for attr in ("_sam_adapter", "_sam_busy", "_pending_sam_image", "_image_path"):
        assert hasattr(page, attr), f"LabelPage 缺 SAM 宿主态 {attr}（Mixin 契约失守）"


@pytest.mark.unit
def test_sam_session_load_uses_resolve_device():
    """W21 源码守卫随迁移：SAM 加载 device 走 resolve_device 契约。

    断言本体与 tests/test_sam_adapter.py TestSamDeviceWiring 一致，
    仅文件目标随代码迁移改指 sam_session.py。
    """
    assert SAM_SESSION.is_file()
    load_lines = [
        ln for ln in SAM_SESSION.read_text(encoding="utf-8").splitlines()
        if "adapter.load(" in ln
    ]
    assert load_lines, "sam_session 应有 adapter.load( 调用"
    assert any("resolve_device" in ln for ln in load_lines), (
        f"SAM 加载须走 resolve_device 契约，实际: {load_lines}"
    )
