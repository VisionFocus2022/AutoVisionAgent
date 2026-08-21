"""W26 毒化运行时门禁（双审整改入库）。

把 W26 排除决策的一次性毒化取证（sys.modules 钉 None 模拟 exe 内
模块缺失）固化为常驻门禁：任何未来波次把 purged 家族拉进产品
import 链（直接或经载荷三方包顶层），本测试立刻红——而不是等到
下一次 exe UIA 真窗才发现（matplotlib 事故的教训：venv 有包掩盖
打包态缺失，单测层永远绿）。

覆盖面（与 W26 一次性取证同口径，均 import 级）：
  1. 九引擎注册全链（models.supervised.engines.register_all_engines）
  2. anomalib / huggingface_hub 顶层（abdet 引擎依赖链）
  3. ultralytics YOLO 符号导入（det/pseg/pose 引擎依赖链）
"""
import sys

import pytest

PURGED = ("gradio", "fastapi", "flask", "uvicorn", "dash", "pydub", "pytest", "_pytest")


@pytest.fixture
def _block_purged(monkeypatch):
    # sys.modules[name]=None → import 即 ImportError，等价 exe 内模块缺失；
    # 对 find_spec/importlib.metadata 路径比真实排除更严（venv 元数据仍在），可接受
    for name in PURGED:
        monkeypatch.setitem(sys.modules, name, None)


@pytest.mark.unit
def test_engines_register_without_purged_modules(_block_purged):
    """引擎注册链在 purged 家族缺失下必须完整走通。"""
    from models.supervised.engines import register_all_engines
    from models.supervised.registry import get_default_registry

    register_all_engines()
    reg = get_default_registry()
    from core.interfaces_supervised import TaskType

    for task in TaskType:
        assert reg.has(task), f"{task} 引擎注册失败——purged 家族已渗入注册链"


@pytest.mark.unit
def test_load_bearing_third_party_imports_without_purged_modules(_block_purged):
    """载荷三方包顶层导入链在 purged 家族缺失下必须走通。"""
    import anomalib  # noqa: F401
    import huggingface_hub  # noqa: F401
    from ultralytics import YOLO  # noqa: F401
