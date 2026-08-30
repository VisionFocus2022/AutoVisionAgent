"""W32（W26 计划 P2）：OCR 可选引擎——easyocr 惰性接入 + 离线供给 + 单 cv2 守卫。

可选任务设计：引擎注册零成本（模块级不触 easyocr），加载/推理惰性导入；
缺库/缺权重诚实 raise（带 scripts/fetch_ocr_weights.py 离线指引）；
lite 发行版明确排除 easyocr（推理-only 可选件，不占 2GiB 预算）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ============================== 1. 注册与惰性 ============================== #


@pytest.mark.unit
def test_ocr_engine_registers_without_easyocr(monkeypatch):
    """模块级不触 easyocr：毒化后 register_all_engines 仍注册 OCR。"""
    import models.supervised.engines as engines_pkg
    from core.interfaces_supervised import TaskType
    from models.supervised.registry import get_default_registry

    monkeypatch.setitem(sys.modules, "easyocr", None)
    engines_pkg.register_all_engines()
    assert get_default_registry().has(TaskType.OCR) is True


@pytest.mark.unit
def test_ocr_tasktype_serializes_as_string():
    """proto 零改动：task 序列化为字符串值 "ocr"。"""
    from core.interfaces_supervised import TaskType

    assert TaskType("ocr") is TaskType.OCR
    assert TaskType.OCR.value == "ocr"


# ============================== 2. 诚实失败路径 ============================== #


@pytest.mark.unit
def test_ocr_load_missing_easyocr_honest_raise(monkeypatch):
    """缺 easyocr 库 → SupervisedEngineError 带安装/离线指引。"""
    from core.exceptions import SupervisedEngineError
    from models.supervised.engines.ocr_easyocr import OcrEasyocrEngine

    monkeypatch.setitem(sys.modules, "easyocr", None)
    with pytest.raises(SupervisedEngineError, match="easyocr"):
        OcrEasyocrEngine().load("", device="cpu")


@pytest.mark.unit
def test_ocr_load_missing_weights_offline_honest_raise(monkeypatch):
    """离线权重目录缺权重（Reader 报错）→ SupervisedEngineError 带
    fetch_ocr_weights 指引（不静默不返假数据）。"""
    from core.exceptions import SupervisedEngineError
    from models.supervised.engines import ocr_easyocr

    class _BoomReader:
        def __init__(self, *a, **k):
            raise FileNotFoundError("craft_mlt_25k.pth not found")

    fake_easyocr = type(sys)("easyocr")
    fake_easyocr.Reader = _BoomReader
    monkeypatch.setitem(sys.modules, "easyocr", fake_easyocr)
    monkeypatch.setattr(ocr_easyocr, "resolve_device", lambda d: "cpu")

    with pytest.raises(SupervisedEngineError, match="fetch_ocr_weights"):
        ocr_easyocr.OcrEasyocrEngine().load("Z:/offline/weights", device="cpu")


@pytest.mark.unit
def test_ocr_infer_before_load_raises():
    from core.exceptions import SupervisedEngineError
    from models.supervised.engines.ocr_easyocr import OcrEasyocrEngine

    with pytest.raises(SupervisedEngineError, match="未加载"):
        OcrEasyocrEngine().infer(None)


# ============================== 3. 文本行映射 ============================== #


@pytest.mark.unit
def test_ocr_infer_maps_text_lines_to_xyxy(monkeypatch, tmp_path):
    """四点 quad → xyxy 框；labels=识别串；scores=逐行置信度；threshold 过滤。"""
    import numpy as np

    from core.interfaces_supervised import TaskType
    from models.supervised.engines import ocr_easyocr

    class _FakeReader:
        def readtext(self, image, detail=1):
            return [
                ([[10, 5], [40, 5], [40, 25], [10, 25]], "LOT-2024", 0.97),
                ([[1, 1], [2, 1], [2, 2], [1, 2]], "low-conf", 0.10),
                ([[60, 30], [90, 30], [90, 50], [60, 50]], "NG", 0.80),
            ]

    fake_easyocr = type(sys)("easyocr")
    fake_easyocr.Reader = lambda *a, **k: _FakeReader()
    monkeypatch.setitem(sys.modules, "easyocr", fake_easyocr)
    monkeypatch.setattr(ocr_easyocr, "resolve_device", lambda d: "cpu")

    engine = ocr_easyocr.OcrEasyocrEngine()
    engine.load(str(tmp_path), device="cpu")
    result = engine.infer(np.zeros((60, 100, 3), dtype=np.uint8), threshold=0.5)

    assert result.task is TaskType.OCR
    assert result.boxes == ((10.0, 5.0, 40.0, 25.0), (60.0, 30.0, 90.0, 50.0))
    assert result.labels == ("LOT-2024", "NG")
    assert result.scores == (0.97, 0.80), "低置信行须被 threshold 过滤"


# ============================== 4. lock 单 cv2 守卫 ============================== #


@pytest.mark.unit
def test_lock_single_cv2_provider():
    """requirements.lock.txt 唯一 cv2 provider（opencv-contrib-python）——
    easyocr 元数据拉 opencv-python-headless 会双源冲突（v1.x 血泪）。"""
    text = (REPO_ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    providers = [
        ln for ln in text.splitlines()
        if ln.strip().lower().startswith(("opencv-python", "opencv-contrib-python"))
    ]
    assert providers == ["opencv-contrib-python==4.13.0.92"], (
        f"cv2 必须单源 opencv-contrib-python，实际: {providers}"
    )
    assert "easyocr" in text, "可选 OCR 依赖须在 lock 留档（版本钉住）"


# ============================== 5. GUI 面：训练页排除 + 脚本在场 ============================== #


@pytest.mark.unit
def test_train_page_combo_excludes_ocr(qapp=None):
    """训练页不支持 OCR 训练——下拉不列（推理-only 任务）。"""
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox

    QApplication.instance() or QApplication([])
    from core.interfaces_supervised import TaskType
    from gui.core.tasks_ui import populate_task_combo

    combo = QComboBox()
    populate_task_combo(combo, exclude=(TaskType.OCR,))
    datas = [combo.itemData(i) for i in range(combo.count())]
    assert TaskType.OCR not in datas
    assert TaskType.DET in datas  # 其余任务不受影响


@pytest.mark.unit
def test_predict_combo_lists_ocr_when_registered():
    """推理页 only_available 语义：OCR 引擎注册即在列（可选任务直达）。"""
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox

    QApplication.instance() or QApplication([])
    from core.interfaces_supervised import TaskType
    from gui.core.tasks_ui import populate_task_combo

    combo = QComboBox()
    populate_task_combo(combo, only_available=True)
    datas = [combo.itemData(i) for i in range(combo.count())]
    assert TaskType.OCR in datas


@pytest.mark.unit
def test_fetch_weights_script_exists_and_documents_sha256():
    """离线供给脚本在场且文档化 sha256 manifest（离线优先平台显式供给）。"""
    script = REPO_ROOT / "scripts" / "fetch_ocr_weights.py"
    assert script.is_file(), "scripts/fetch_ocr_weights.py 应存在（W32）"
    src = script.read_text(encoding="utf-8")
    assert "sha256" in src.lower(), "脚本须文档化/产出 sha256 manifest"
