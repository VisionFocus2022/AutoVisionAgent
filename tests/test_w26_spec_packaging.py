"""W26 spec 打包守卫（P0 打包修复）。

锁定两个耦合打包缺陷的 pytest 层前置守卫：

  1. matplotlib 误排除（W25 UIA 真窗首跑擒获，单测层不可见）：
     spec excludes 剔除 matplotlib，但 ultralytics 导入链硬依赖
     （ultralytics/models/yolo/semantic/train.py:8 顶层 import
     matplotlib.pyplot）→ 打包态 predict 引擎加载必败且
     ModuleNotFoundError 逃出页面 except 元组。.venv 装有 matplotlib
     故单测层永远绿——只有 exe 真窗（UIA）能暴露。修复 = excludes
     去 matplotlib + 重打包（体积测算：净增 ~16-19MiB < lite 余量
     30.8MiB，Agg-only 回退杠杆备而不用）。

  2. PYZ 静态误拉 pytest 运行时（79 模块）与 pydub 链（W24 审计在案）：
     产品代码零引用，纯体积浪费。修复 = excludes 增补 pytest/_pytest/pydub。

排除的构造性安全前提：spec excludes 内任何模块不得被产品源码 import
（AST 级扫描，不匹配注释/字符串——排除一个被引用的模块 = 打包态
静默 ImportError，正是缺陷 1 的镜像事故面）。

红线（v1.x 血泪教训）：严禁排除 unittest——torch 2.5+ 运行时依赖
unittest.mock，v1.x 曾因排除 unittest 导致打包态启动即崩。
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = REPO_ROOT / "autovisionagent.spec"

# 产品发布包（与 pytest.ini --cov 门禁包同口径；scripts/tests 不算产品面）
PRODUCT_PACKAGES = (
    "core",
    "dataset",
    "project",
    "models",
    "labeling",
    "training",
    "inference",
    "evaluation",
    "exporter",
    "industrial_vision_platform",
    "serving",
    "gui",
)

# W26 确认需排除的 venv-only 运行时（PYZ 实证在场 + 产品零引用 +
# 毒化测试构造性安全：屏蔽全家后 register_all_engines/anomalib 顶层/
# ultralytics yolov8n load+infer 全链通过——引用根均在死支）
PURGED_RUNTIME_MODULES = (
    "pytest",
    "_pytest",
    "pydub",
    "gradio",
    "fastapi",
    "flask",
    "uvicorn",
)


def _parse_spec_excludes(source: str) -> set:
    """从 autovisionagent.spec 提取 Analysis(excludes=[...]) 字面量。

    与 test_dynamic_import_guard._parse_spec_hiddenimports 同款 AST
    解析（spec 是可执行 python 但含 PyInstaller 全局名，不能 import 执行）。
    严格化（W26 双审整改）：元素必须全为字符串常量（防 [*BASE, ...]
    动态拼装使条目对守卫不可见）；Analysis(excludes=) 必须恰 1 处
    （防未来多 bundle spec 时静默只盯其一）。
    """
    matches: list = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if func_name != "Analysis":
            continue
        for kw in node.keywords:
            if kw.arg != "excludes":
                continue
            elts = getattr(kw.value, "elts", None)
            assert elts is not None, "spec excludes 不是字面量列表"
            assert all(
                isinstance(e, ast.Constant) and isinstance(e.value, str)
                for e in elts
            ), "spec excludes 含非字符串常量元素——动态拼装会使条目对守卫不可见"
            matches.append({e.value for e in elts})
    assert len(matches) == 1, (
        f"spec 中 Analysis(excludes=...) 应为恰 1 处，实测 {len(matches)} 处"
        "——多 bundle 时守卫口径需显式选择"
    )
    return matches[0]


def _product_imported_modules() -> set:
    """产品源码 import 的顶层模块名全集（AST 级，含函数内惰性导入）。

    PyInstaller 静态分析同样追踪函数体内的 import 语句——守卫口径
    必须覆盖惰性导入，否则"产品零引用"结论失真。
    """
    names: set = set()
    for pkg in PRODUCT_PACKAGES:
        for py in (REPO_ROOT / pkg).rglob("*.py"):
            names.update(_module_import_tops(py.read_text(encoding="utf-8")))
    entry = REPO_ROOT / "gui" / "main.py"
    names.update(_module_import_tops(entry.read_text(encoding="utf-8")))
    return names


def _module_import_tops(source: str) -> set:
    """单文件 import 的顶层模块名（AST 级，含函数内惰性导入与
    importlib/__import__ 常量调用）。

    PyInstaller 静态分析同样追踪函数体内的 import 语句——守卫口径
    必须覆盖惰性导入，否则"产品零引用"结论失真。
    """
    names: set = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            fname = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if fname in ("import_module", "__import__") and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    names.add(arg0.value.split(".")[0])
    return names


@pytest.mark.unit
def test_spec_includes_matplotlib():
    """缺陷 1 修复锚：matplotlib 不得在 excludes（ultralytics 硬依赖）。

    历史教训：W19 为瘦身排除 matplotlib 时未察觉 ultralytics
    semantic/train.py 顶层导入链，打包态 predict 引擎加载必败，
    直到 W25 UIA 真窗才暴露（.venv 有 matplotlib 掩盖单测层）。
    """
    excludes = _parse_spec_excludes(SPEC_FILE.read_text(encoding="utf-8"))
    assert "matplotlib" not in excludes, (
        "spec excludes 含 matplotlib——ultralytics 导入链硬依赖"
        "（semantic/train.py:8），打包态引擎加载必败（W25 UIA 擒获）。"
        "体积补偿由 pytest/pydub 清场承担，Agg-only 回退见 W26 文档。"
    )


@pytest.mark.unit
def test_spec_purges_pytest_runtime():
    """缺陷 2 修复锚：pytest 运行时（79 模块）不得入 PYZ。"""
    excludes = _parse_spec_excludes(SPEC_FILE.read_text(encoding="utf-8"))
    missing = {"pytest", "_pytest"} - excludes
    assert not missing, (
        f"spec excludes 缺 {sorted(missing)}——PYZ 将静态误拉完整 pytest "
        f"运行时（W24 审计 79 模块），产品代码零引用纯体积浪费"
    )


@pytest.mark.unit
def test_spec_purges_pydub():
    """缺陷 2 修复锚：pydub 链不得入 PYZ（W24 审计在案）。"""
    excludes = _parse_spec_excludes(SPEC_FILE.read_text(encoding="utf-8"))
    assert "pydub" in excludes, (
        "spec excludes 缺 pydub——PYZ 将误拉 pydub 链，产品代码零引用"
    )


@pytest.mark.unit
def test_spec_purges_web_stack():
    """W26 扩面：gradio/fastapi/flask/uvicorn 不得入 PYZ。

    PYZ 实证：gradio 169 + fastapi 39 + flask 23 + uvicorn 40 模块
    （starlette/httpx 等伴生树随根消失自动脱落）。安全性三重证据：
    产品源零 import（下方安检）+ W26 毒化测试（tests/test_w26_poison_runtime.py
    常驻门禁：屏蔽全家后 register_all_engines/anomalib/huggingface_hub
    顶层/ultralytics YOLO 导入全过）。引用根实测（W26 双审纠正，勿再
    归因 anomalib）：huggingface_hub._webhooks_server/_oauth（惰性/
    TYPE_CHECKING）、lightning.pytorch.serve、transformers.cli.serving、
    ultralytics.solutions.similarity_search（惰性 flask）——均为
    桌面产品流程不会执行的死支。
    注意：pydantic/huggingface_hub 虽为 web 家族近邻但 anomalib
    正当引用，严禁加入排除。
    """
    excludes = _parse_spec_excludes(SPEC_FILE.read_text(encoding="utf-8"))
    missing = {"gradio", "fastapi", "flask", "uvicorn"} - excludes
    assert not missing, (
        f"spec excludes 缺 {sorted(missing)}——PYZ 将误拉 web 服务栈"
        f"（~270 模块），产品流程零引用（毒化测试实证）"
    )


@pytest.mark.unit
def test_spec_never_excludes_unittest():
    """红线守卫：严禁排除 unittest（torch 2.5+ 运行时依赖 unittest.mock）。

    v1.x 血泪教训：排除 unittest → 打包态启动即崩（torch 导入链
    依赖 unittest.mock）。本守卫防未来"瘦身"波次误伤。
    """
    excludes = _parse_spec_excludes(SPEC_FILE.read_text(encoding="utf-8"))
    offenders = {
        m for m in excludes if m == "unittest" or m.startswith("unittest.")
    }
    assert not offenders, (
        f"spec excludes 含 {sorted(offenders)}——torch 2.5+ 运行时依赖 "
        f"unittest.mock，排除将导致打包态启动即崩（v1.x 教训）"
    )


@pytest.mark.unit
def test_product_never_imports_excluded_modules():
    """排除的构造性安全前提：产品源码零 import 任何 excluded 模块。

    排除一个被产品引用的模块 = 打包态静默 ImportError（缺陷 1 的
    镜像事故面）。AST 级扫描覆盖函数内惰性导入（PyInstaller 静态
    分析同口径）。任何未来 excludes 增补都被本守卫强制过安检。
    """
    excludes = _parse_spec_excludes(SPEC_FILE.read_text(encoding="utf-8"))
    imported = _product_imported_modules()
    offenders = imported & excludes
    assert not offenders, (
        f"产品源码 import 了被 excludes 的模块 {sorted(offenders)}——"
        f"打包态将静默 ImportError；要么去掉该 import，要么移出 excludes"
    )


# W26 双审整改：W19 事故机制机械化——产品零引用守卫看不见
# "第三方库顶层 import 被 excludes"（matplotlib 正是此型：产品不
# import 它，唯一引用是 ultralytics 的模块级导入）。本守卫扫描
# 载荷第三方包的【模块级】导入面（函数体内死支不算——PyInstaller
# 会拉入但运行时不执行，清场正是为此）， intersects excludes 即红。
VENDORED_LOAD_BEARING = (
    "ultralytics",
    "anomalib",
    "lightning",
    "pytorch_lightning",
    "huggingface_hub",
    "transformers",
    "supervision",
    "matplotlib",
)

_BUILD_PYZ = REPO_ROOT / "build" / "autovisionagent" / "PYZ-00.pyz"


def _pyz_module_names() -> set | None:
    """当前构建 PYZ 的模块名全集（无构建产物时 None）。"""
    if not _BUILD_PYZ.is_file():
        return None
    from PyInstaller.archive.readers import ZlibArchiveReader

    return set(ZlibArchiveReader(str(_BUILD_PYZ)).toc)


def _vendored_module_level_import_tops() -> dict:
    """载荷第三方包各自被【顶层 import 语句】引用的模块名全集。

    仅扫模块级（AST body 直属）——函数体/TYPE_CHECKING/if 内的导入是
    PyInstaller 静态误拉的来源，正是合法排除对象，不计入
    （trainer.py 的 `if is_in_notebook(): from .utils.notebook ...`
    即属此类：exe 内条件恒 False）。
    """
    site = REPO_ROOT / ".venv" / "Lib" / "site-packages"
    result: dict = {}
    for pkg in VENDORED_LOAD_BEARING:
        pkg_dir = site / pkg
        if not pkg_dir.is_dir():
            continue  # 未安装的载荷包（如 transformers 可选）跳过
        tops: set = set()
        for py in pkg_dir.rglob("*.py"):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for stmt in tree.body:
                if isinstance(stmt, ast.Import):
                    tops.update(a.name.split(".")[0] for a in stmt.names)
                elif isinstance(stmt, ast.ImportFrom) and stmt.module and stmt.level == 0:
                    tops.add(stmt.module.split(".")[0])
        result[pkg] = tops
    return result


@pytest.mark.unit
def test_vendored_load_bearing_never_module_level_imports_excluded():
    """W19 教训机械化：excludes 不得命中【已入 PYZ 的】载荷三方包
    文件的模块级导入。

    matplotlib 事故正是此型（产品零引用，但 ultralytics semantic/train.py:8
    模块级 import matplotlib.pyplot）。口径与构建对齐：仅当引用方
    模块确实在当前 PYZ 内才算冲突（.venv 里未入包的死文件不计——
    如 matplotlib.backends.backend_tkagg 顶层 import tkinter，但
    PyInstaller hook 已裁剪后端树未入包）。无构建产物时 skip
    （CI/清洁环境；真产物守卫惯例同 tests/test_w19_lite_dist.py）。
    """
    pyz_names = _pyz_module_names()
    if pyz_names is None:
        pytest.skip("build/autovisionagent/PYZ-00.pyz 不存在——真产物守卫需开发机构建后在案")
    vendored = _vendored_module_level_import_tops()
    excludes = _parse_spec_excludes(SPEC_FILE.read_text(encoding="utf-8"))
    offenders = {}
    for pkg, tops in vendored.items():
        hits = sorted(tops & excludes)
        if not hits:
            continue
        hit_set = set(hits)
        # 该包哪些【已入 PYZ 的】文件持有这些顶层导入
        site = REPO_ROOT / ".venv" / "Lib" / "site-packages"
        files = []
        for py in (site / pkg).rglob("*.py"):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for stmt in tree.body:
                mods = (
                    {a.name.split(".")[0] for a in stmt.names}
                    if isinstance(stmt, ast.Import)
                    else {stmt.module.split(".")[0]}
                    if isinstance(stmt, ast.ImportFrom) and stmt.module and stmt.level == 0
                    else set()
                )
                if mods & hit_set:
                    mod = ".".join(py.with_suffix("").parts[len(site.parts) :])
                    if mod in pyz_names:
                        files.append(mod)
                    break
        if files:
            offenders[pkg] = {"excluded_hits": hits, "pyz_files": files[:5]}
    assert not offenders, (
        f"已入 PYZ 的载荷三方包文件模块级 import 了被 excludes 的模块："
        f"{offenders}——打包态 import 链必炸（W19 matplotlib 事故同型）。"
        f"要么移出 excludes，要么外科排除该引用方模块（如"
        f"transformers.utils.notebook 先例）"
    )


def _parse_spec_datas(source: str) -> set:
    """从 Analysis(datas=...) 递归收集字面量 (src, dst) 元组。

    datas 允许 ``[] + ([...] if ... else [])`` 拼接形态（configs 先例），
    故走 ast.walk 收集关键字值子树内全部字符串二元 Tuple 常量——
    动态拼装条目（非字面量）守卫天然不可见，与 hiddenimports 守卫同边界。
    """
    tuples: set = set()
    found = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if func_name != "Analysis":
            continue
        for kw in node.keywords:
            if kw.arg != "datas":
                continue
            found += 1
            for sub in ast.walk(kw.value):
                if (
                    isinstance(sub, ast.Tuple)
                    and len(sub.elts) == 2
                    and all(
                        isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in sub.elts
                    )
                ):
                    tuples.add((sub.elts[0].value, sub.elts[1].value))
    assert found == 1, (
        f"spec 中 Analysis(datas=...) 应为恰 1 处，实测 {found}"
        "——多 bundle 时守卫口径需显式选择"
    )
    return tuples


@pytest.mark.unit
def test_spec_datas_bundles_sam3_weights():
    """SAM3 权重 datas 锚（2026-09-01 spec datas 纳入批 FR-004）。

    weights/sam3 必须在 datas——否则每次重打包产出无 SAM3 权重的 exe
    （自动发现落空→弹窗），须手动 robocopy 3.21GiB 补救（08-31 权宜态）。
    """
    datas = _parse_spec_datas(SPEC_FILE.read_text(encoding="utf-8"))
    assert ("weights/sam3", "weights/sam3") in datas, (
        "spec datas 缺 weights/sam3——重打包产物将不带 SAM3 权重，"
        "自动发现退化为手选对话框（上批 08-31 手动复制权宜态回归）。"
        "缺失防呆断言在 spec 头部（BUILD-ABORT），本守卫锁 datas 条日本体。"
    )
