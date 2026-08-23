"""W27（W26 计划）：predict 页批量/序列化 worker 抽取的行为保持守卫。

背景：gui/pages/predict/page.py W24 实测 784 行（≤800 仅 16 行余量）——
W28 阈值接入与 W33 批量产物扩展都会落此页，不先抽必撞 ≤800 守卫硬失败
（反棘轮断言禁临时豁免）。W27 把纯函数层抽至 gui/pages/predict/workers.py
（仿 data_manage/workers.py 模式），页面只剩 UI 装配与信号接线。
"""
import ast
import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKERS = REPO_ROOT / "gui" / "pages" / "predict" / "workers.py"
PAGE = REPO_ROOT / "gui" / "pages" / "predict" / "page.py"


@pytest.mark.unit
def test_workers_module_exists_and_qt_free():
    """workers.py 在场且零 Qt 依赖（纯函数层）。"""
    assert WORKERS.is_file(), "gui/pages/predict/workers.py 应存在（W27 抽取）"
    tree = ast.parse(WORKERS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("PySide6") for a in node.names), (
                f"workers.py 不得 import Qt: {[a.name for a in node.names]}"
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("PySide6"), (
                f"workers.py 不得 from-import Qt: {node.module}"
            )


@pytest.mark.unit
def test_workers_expects_pure_helpers():
    """workers.py 提供批量收集/记录序列化/原子写盘/CSV 防注入纯函数。

    W39·v6 P2-8：atomic_write_json 收敛为 labeling.batch_tools 单源
    （mkstemp 强版），本模块经 import 再导出——模块面仍暴露该名，
    batch_runner 与测试 monkeypatch 缝不变。
    """
    import gui.pages.predict.workers as workers_mod

    tree = ast.parse(WORKERS.read_text(encoding="utf-8"))
    funcs = {
        n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "sanitize_csv_cell",
        "boxes_to_jsonable",
        "collect_images",
        "batch_save_dir",
        "result_to_record",
        "row_display_fields",
    } <= funcs
    assert callable(workers_mod.atomic_write_json), (
        "atomic_write_json 须从 labeling.batch_tools 再导出（单源收敛后缝不变）"
    )


@pytest.mark.unit
def test_collect_images_recursive_and_order(tmp_path):
    """递归收集 + 保持 os.walk 原序（抽取前行为——数据管理页另有排序层）。"""
    from gui.pages.predict.workers import collect_images

    (tmp_path / "sub").mkdir()
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "sub" / "b.jpg").write_bytes(b"x")
    (tmp_path / "ignore.txt").write_bytes(b"x")
    got = collect_images(str(tmp_path))
    assert len(got) == 2
    assert all(p.replace("\\", "/").endswith((".png", ".jpg")) for p in got)


@pytest.mark.unit
def test_boxes_to_jsonable_numpy_and_plain():
    """ndarray 走 tolist、普通序列走逐行 list、None 透传（W7/W9 语义）。"""
    from gui.pages.predict.workers import boxes_to_jsonable

    class _FakeArray(list):
        def tolist(self):  # 模拟 numpy 接口
            return [[1.0, 2.0], [3.0, 4.0]]

    assert boxes_to_jsonable(None) is None
    assert boxes_to_jsonable(_FakeArray([[9]])) == [[1.0, 2.0], [3.0, 4.0]]
    assert boxes_to_jsonable(((1, 2), (3, 4))) == [[1, 2], [3, 4]]


@pytest.mark.unit
def test_atomic_write_json_replaces_and_cleans_tmp(tmp_path):
    """原子写：目标更新、.tmp 不残留、异常时旧内容不损。"""
    from gui.pages.predict.workers import atomic_write_json

    target = tmp_path / "r.json"
    atomic_write_json(str(target), {"a": 1})
    atomic_write_json(str(target), {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_sanitize_csv_cell_injection_guard():
    from gui.pages.predict.workers import sanitize_csv_cell

    assert sanitize_csv_cell("=SUM(A1)") == "'=SUM(A1)"
    assert sanitize_csv_cell("+1") == "'+1"
    assert sanitize_csv_cell("normal") == "normal"
    assert sanitize_csv_cell(123) == 123


@pytest.mark.unit
def test_page_uses_workers_not_inline():
    """page.py 引用 workers（防未来把逻辑内联回页面）。"""
    src = PAGE.read_text(encoding="utf-8")
    assert "from gui.pages.predict.workers import" in src or "from .workers import" in src
    assert "_CSV_INJECTION_CHARS" not in src, "注入防护常量应住在 workers.py"
