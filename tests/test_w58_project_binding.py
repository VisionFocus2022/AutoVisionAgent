"""W58-A（FR-005）：工程参数绑定三段（对标 .spro predictionParams/transferType/dataPath）。

覆盖：binding 读写往返与容错（缺文件/损坏/非字典/非法 transfer_type） /
任务→默认标注形态推导 / store 创建即写默认 binding / 预测页带入与保存 /
label 页 transferType 联动。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import TaskType  # noqa: E402
from labeling import AnnotationMode  # noqa: E402
from project.binding import (  # noqa: E402
    ProjectBinding,
    binding_path,
    default_transfer_type,
    read_binding,
    write_binding,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ============================== binding 读写 ============================== #


@pytest.mark.unit
def test_read_binding_missing_file_returns_defaults(tmp_path):
    assert read_binding(tmp_path) == ProjectBinding()


@pytest.mark.unit
def test_binding_roundtrip(tmp_path):
    binding = ProjectBinding(
        model_file="models/best.pt", threshold=0.35,
        transfer_type="Polygon", data_path=str(tmp_path),
    )
    write_binding(tmp_path, binding)
    assert binding_path(tmp_path).exists()
    assert read_binding(tmp_path) == binding


@pytest.mark.unit
def test_read_binding_corrupt_json_returns_defaults(tmp_path):
    binding_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert read_binding(tmp_path) == ProjectBinding()


@pytest.mark.unit
def test_read_binding_non_dict_returns_defaults(tmp_path):
    binding_path(tmp_path).write_text("[1, 2]", encoding="utf-8")
    assert read_binding(tmp_path) == ProjectBinding()


@pytest.mark.unit
def test_read_binding_invalid_transfer_type_ignored(tmp_path):
    write_binding(tmp_path, ProjectBinding(transfer_type="Zigzag"))
    assert read_binding(tmp_path).transfer_type is None


@pytest.mark.unit
def test_default_transfer_type_by_task():
    assert default_transfer_type(TaskType.DET) == "Rect"
    assert default_transfer_type(TaskType.CLS) == "Rect"
    assert default_transfer_type(TaskType.SEG) == "Polygon"
    assert default_transfer_type(TaskType.PSEG) == "Polygon"
    assert default_transfer_type(TaskType.SSEG) == "Polygon"


# ============================== store 创建即写 ============================== #


@pytest.mark.unit
def test_store_create_project_writes_default_binding(tmp_path):
    from project.store import FileSystemProjectStore

    store = FileSystemProjectStore(str(tmp_path))
    pid, layout = store.create_project("pseg_demo", TaskType.PSEG)

    binding = read_binding(layout.root)
    assert binding.transfer_type == "Polygon"
    assert binding.data_path == layout.root
    assert binding.model_file == ""

    pid2, layout2 = store.create_project("det_demo", TaskType.DET)
    assert read_binding(layout2.root).transfer_type == "Rect"


# ============================== 预测页带入/保存 ============================== #


@pytest.fixture()
def predict_page(qapp, tmp_path):
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    page._project_dir = str(tmp_path)
    yield page
    page.deleteLater()


@pytest.mark.unit
def test_predict_bring_from_project_fills_model_and_threshold(
        predict_page, tmp_path, monkeypatch):
    model_file = tmp_path / "m.pt"
    model_file.write_bytes(b"weights")
    write_binding(
        tmp_path, ProjectBinding(model_file=str(model_file), threshold=0.35)
    )
    called = {}
    monkeypatch.setattr(
        predict_page, "_load_model_from",
        lambda path: called.update(path=path),
    )
    predict_page._bring_from_project()
    assert called.get("path") == str(model_file)
    assert abs(predict_page.spin_threshold.value() - 0.35) < 1e-9


@pytest.mark.unit
def test_predict_bring_without_model_binding_is_honest(predict_page, tmp_path):
    msgs: list[tuple[str, str]] = []
    predict_page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    write_binding(tmp_path, ProjectBinding())  # 无 model_file
    predict_page._bring_from_project()
    assert any("工程未绑定模型" in t or "工程未绑定模型" in a for t, a in msgs)


@pytest.mark.unit
def test_predict_save_binding_preserves_other_fields(predict_page, tmp_path):
    write_binding(
        tmp_path, ProjectBinding(transfer_type="Polygon", data_path="keep")
    )
    predict_page._model_path = "best.pt"
    predict_page.spin_threshold.setValue(0.42)
    predict_page._save_binding()
    binding = read_binding(tmp_path)
    assert binding.model_file == "best.pt"
    assert abs(binding.threshold - 0.42) < 1e-9
    assert binding.transfer_type == "Polygon"  # 读改写保留
    assert binding.data_path == "keep"


@pytest.mark.unit
def test_from_project_button_enabled_after_project(predict_page):
    assert predict_page.btn_from_project.isEnabled()


# ============================== label 页联动 ============================== #


@pytest.mark.unit
def test_label_transfer_type_links_default_mode(qapp, tmp_path):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    write_binding(tmp_path, ProjectBinding(transfer_type="Rect"))
    page.set_project_dir(str(tmp_path))
    assert page.controller.mode is AnnotationMode.RECTANGLE

    write_binding(tmp_path, ProjectBinding(transfer_type="Polygon"))
    page.set_project_dir(str(tmp_path))
    assert page.controller.mode is AnnotationMode.POLYGON
    page.deleteLater()


@pytest.mark.unit
def test_label_no_binding_keeps_current_mode(qapp, tmp_path):
    from gui.pages.label.page import LabelPage

    page = LabelPage()
    page.set_default_shape_mode(AnnotationMode.CUT_LINE)
    page.set_project_dir(str(tmp_path))  # 无 binding.json
    assert page.controller.mode is AnnotationMode.CUT_LINE
    page.deleteLater()
