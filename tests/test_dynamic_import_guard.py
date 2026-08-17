"""动态导入离线守卫（W14 C5 P2-10）。

守护五份"手工双列表"的一致性——任何一方漂移立即红：
  1. labeling/modes/__init__.py 的标注器模块列表（变量拼接 importlib，
     PyInstaller 静态分析不可见）
  2. labeling/modes/ 目录实际模块
  3. models/supervised/engines/__init__.py 的引擎模块列表
     （register_all_engines 内 __import__ 惰性加载）
  4. models/supervised/engines/ 目录实际模块
  5. autovisionagent.spec 的 hiddenimports（PyInstaller 打包真源）

背景（v2 审查 P2-10）：W4 发版检查曾因 modes 漏打包导致 exe 内全部手动
标注失效（UIA 软通过掩盖，最慢反馈层才暴露）。本守卫把反馈层从
"发版人工步骤"提前到 pytest 门禁。

另守卫 labeling/canvas.py 不得使用 __import__ 动态导入（常量字符串且
顶部已静态 import PySide6.QtCore——P2-10 要求静态化）。
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

MODES_INIT = REPO_ROOT / "labeling" / "modes" / "__init__.py"
ENGINES_INIT = REPO_ROOT / "models" / "supervised" / "engines" / "__init__.py"
SPEC_FILE = REPO_ROOT / "autovisionagent.spec"
CANVAS_FILE = REPO_ROOT / "labeling" / "canvas.py"

_MODES_PREFIX = "labeling.modes."
_ENGINES_PREFIX = "models.supervised.engines."


# ---------------------------------------------------------------------------
# 解析层（被测代码用变量拼 importlib/__import__，静态分析必须走 AST 解析）
# ---------------------------------------------------------------------------

def _public_py_modules(directory: Path) -> set:
    """目录内公开 .py 模块名（排除 __init__ 与 _ 前缀私有辅助模块）。"""
    return {
        p.stem
        for p in directory.glob("*.py")
        if p.stem != "__init__" and not p.stem.startswith("_")
    }


def _parse_mode_modules(source: str) -> set:
    """从 labeling/modes/__init__.py 提取动态导入的模块名。

    形态：for _name, _module_path in [("AutoLabeler", "labeling.modes.auto"), ...]
    """
    names = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.List):
            continue
        for elt in node.elts:
            if (
                isinstance(elt, ast.Tuple)
                and len(elt.elts) == 2
                and all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str)
                    for e in elt.elts
                )
            ):
                module_path = elt.elts[1].value
                if module_path.startswith(_MODES_PREFIX):
                    names.add(module_path[len(_MODES_PREFIX):])
    assert names, (
        "未能从 labeling/modes/__init__.py 解析出动态导入列表——"
        "若列表形态变更，请同步更新本解析器"
    )
    return names


def _parse_engine_modules(source: str) -> set:
    """从 engines/__init__.py 提取 _engine_modules 字符串列表。"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and "engine_module" in target.id
                    and isinstance(node.value, ast.List)
                    and all(
                        isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in node.value.elts
                    )
                ):
                    return {e.value for e in node.value.elts}
    raise AssertionError(
        "未能从 models/supervised/engines/__init__.py 解析出 _engine_modules——"
        "若列表形态变更，请同步更新本解析器"
    )


def _parse_spec_hiddenimports(source: str) -> set:
    """从 autovisionagent.spec 提取 Analysis(hiddenimports=[...]) 字面量。"""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if func_name != "Analysis":
            continue
        for kw in node.keywords:
            if kw.arg != "hiddenimports":
                continue
            elts = getattr(kw.value, "elts", None)
            assert elts is not None, "spec hiddenimports 不是字面量列表"
            return {
                e.value
                for e in elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    raise AssertionError("未能在 autovisionagent.spec 中找到 Analysis(hiddenimports=...)")


# ---------------------------------------------------------------------------
# 一致性断言层（单入口，供正式用例与"探针红"用例共用）
# ---------------------------------------------------------------------------

def _assert_five_way_consistency() -> None:
    """五方一致性：modes 列表 ↔ modes 目录 ↔ engines 列表 ↔ engines 目录 ↔ spec。"""
    mode_modules = _parse_mode_modules(MODES_INIT.read_text(encoding="utf-8"))
    engine_modules = _parse_engine_modules(ENGINES_INIT.read_text(encoding="utf-8"))
    spec_hidden = _parse_spec_hiddenimports(SPEC_FILE.read_text(encoding="utf-8"))
    modes_dir = _public_py_modules(MODES_INIT.parent)
    engines_dir = _public_py_modules(ENGINES_INIT.parent)

    assert mode_modules == modes_dir, (
        f"标注器列表与 labeling/modes/ 目录漂移："
        f"列表={sorted(mode_modules)} 目录={sorted(modes_dir)}"
    )
    assert engine_modules == engines_dir, (
        f"引擎列表与 engines/ 目录漂移："
        f"列表={sorted(engine_modules)} 目录={sorted(engines_dir)}"
    )

    spec_modes = {
        h[len(_MODES_PREFIX):] for h in spec_hidden if h.startswith(_MODES_PREFIX)
    }
    spec_engines = {
        h[len(_ENGINES_PREFIX):]
        for h in spec_hidden
        if h.startswith(_ENGINES_PREFIX)
    }
    assert spec_modes == mode_modules, (
        f"spec hiddenimports 与标注器列表漂移："
        f"spec={sorted(spec_modes)} 列表={sorted(mode_modules)}"
        f"（exe 内将静默缺失/冗余标注模块）"
    )
    assert spec_engines == engine_modules, (
        f"spec hiddenimports 与引擎列表漂移："
        f"spec={sorted(spec_engines)} 列表={sorted(engine_modules)}"
        f"（exe 内将静默缺失/冗余引擎模块）"
    )


# ---------------------------------------------------------------------------
# 正式守卫用例
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_five_way_consistency_modes_engines_spec():
    """五方一致性总闸（W4 漏打包事故的 pytest 层前置守卫）。"""
    _assert_five_way_consistency()


@pytest.mark.unit
def test_spec_project_hiddenimports_files_exist():
    """spec 中项目内 hiddenimports 必须对应真实模块文件（防拼写/改名的死条目）。"""
    spec_hidden = _parse_spec_hiddenimports(
        SPEC_FILE.read_text(encoding="utf-8")
    )
    project_prefixes = (
        "labeling.",
        "models.",
        "inference.",
        "dataset.",
        "industrial_vision_platform.",
    )
    missing = []
    for mod in sorted(spec_hidden):
        if not mod.startswith(project_prefixes):
            continue  # 第三方库（PySide6/supervision）不检查
        rel = Path(*mod.split("."))
        if not (REPO_ROOT / rel).with_suffix(".py").exists() and not (
            (REPO_ROOT / rel / "__init__.py").exists()
        ):
            missing.append(mod)
    assert missing == [], f"spec hiddenimports 指向不存在的模块: {missing}"


@pytest.mark.unit
def test_engine_modules_all_register_decorator():
    """目录内每个引擎模块必须包含 @register_engine（自注册契约）。"""
    for py in sorted(ENGINES_INIT.parent.glob("*.py")):
        if py.stem.startswith("_") or py.stem == "__init__":
            continue
        src = py.read_text(encoding="utf-8")
        assert "register_engine" in src, (
            f"{py.name} 缺少 register_engine 自注册——exe 内该引擎将被静默跳过"
        )


@pytest.mark.unit
def test_modes_runtime_import_complete():
    """运行时复核：__init__ 声明的全部标注器实际导入成功（无静默降级）。

    modes/__init__ 的 except ImportError 只 warning 跳过——开发环境全依赖
    在场时 _LABELERS 必须与声明的类名集合完全一致。
    """
    declared_classes = set()
    for node in ast.walk(ast.parse(MODES_INIT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.List):
            for elt in node.elts:
                if (
                    isinstance(elt, ast.Tuple)
                    and len(elt.elts) == 2
                    and all(
                        isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in elt.elts
                    )
                    and elt.elts[1].value.startswith(_MODES_PREFIX)
                ):
                    declared_classes.add(elt.elts[0].value)

    import labeling.modes as modes_pkg

    actually_loaded = set(modes_pkg._LABELERS.keys())
    assert actually_loaded == declared_classes, (
        f"标注器声明={sorted(declared_classes)} 实际加载={sorted(actually_loaded)}"
        f"——存在被 except ImportError 静默跳过的标注器"
    )


@pytest.mark.unit
def test_canvas_no_dynamic_import():
    """labeling/canvas.py 不得使用 __import__ 动态导入（P2-10：常量字符串应静态化）。"""
    tree = ast.parse(CANVAS_FILE.read_text(encoding="utf-8"))
    dyn = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "__import__"
    ]
    assert dyn == [], (
        f"labeling/canvas.py 存在冗余动态导入 __import__（{len(dyn)} 处）——"
        f"常量字符串应改为顶部静态 import"
    )
    # 静态导入必须覆盖动态路径引用的符号（QPointF 来自 PySide6.QtCore）
    src = CANVAS_FILE.read_text(encoding="utf-8")
    assert "QPointF" in _static_qtcore_imports(src), (
        "canvas.py 顶部未静态导入 QPointF（PySide6.QtCore）"
    )


def _static_qtcore_imports(source: str) -> list:
    """提取 canvas.py 顶部 from PySide6.QtCore import 的符号列表。"""
    symbols = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "PySide6.QtCore"
        ):
            symbols.extend(
                a.asname or a.name for a in node.names
            )
    return symbols


# ---------------------------------------------------------------------------
# 探针红：证明守卫真的会报警（monkeypatch 造假日，不触碰真实文件）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_probe_guard_fails_on_ghost_mode_module(monkeypatch):
    """探针：向标注器列表注入不存在的模块名 → 一致性必须 AssertionError。"""
    import sys

    guard = sys.modules[__name__]
    real_parse = guard._parse_mode_modules

    def tampered(source: str) -> set:
        return real_parse(source) | {"ghost_mode"}

    monkeypatch.setattr(guard, "_parse_mode_modules", tampered)
    with pytest.raises(AssertionError, match="标注器列表与 labeling/modes/ 目录漂移"):
        guard._assert_five_way_consistency()


@pytest.mark.unit
def test_probe_guard_fails_on_missing_engine_in_spec(monkeypatch):
    """探针：spec hiddenimports 漏列一个引擎 → 一致性必须 AssertionError。"""
    import sys

    guard = sys.modules[__name__]
    real_parse = guard._parse_spec_hiddenimports

    def tampered(source: str) -> set:
        hidden = set(real_parse(source))
        hidden.discard("models.supervised.engines.det_yolo")
        return hidden

    monkeypatch.setattr(guard, "_parse_spec_hiddenimports", tampered)
    with pytest.raises(AssertionError, match="spec hiddenimports 与引擎列表漂移"):
        guard._assert_five_way_consistency()
