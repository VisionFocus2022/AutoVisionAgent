"""第三轮审查修复回归测试（2026-10-06，labeling L1-L6 + eval/exporter E1/E2/E3/E10/E11/X7/E20）。"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")


# ============================== L1：批量坏 JSON 不崩 ============================== #


@pytest.fixture
def labelme_dir(tmp_path):
    return tmp_path


def _write_labelme(path, label="crack"):
    path.write_text(json.dumps({
        "version": "5.4.3", "imagePath": "x.png",
        "imageHeight": 10, "imageWidth": 10,
        "shapes": [{"label": label, "shape_type": "rectangle",
                    "points": [[1, 1], [5, 5]], "group_id": None, "flags": {}}],
    }), encoding="utf-8")


@pytest.mark.unit
def test_batch_replace_survives_corrupt_json(labelme_dir):
    """L1 核心：损坏 JSON 抛 AnnotationIOError（AppError 子类）→ 被捕获
    跳过，批量任务不崩（旧元组捕不到，实测复现整体崩溃）。"""
    from labeling.batch_tools import batch_replace_label

    _write_labelme(labelme_dir / "good.json")
    (labelme_dir / "bad.json").write_text("{corrupt!!!", encoding="utf-8")
    _write_labelme(labelme_dir / "good2.json")

    count = batch_replace_label(str(labelme_dir), "crack", "scratch")

    assert count == 2, "两个好文件都应被处理（坏文件跳过不崩）"
    doc = json.loads((labelme_dir / "good.json").read_text(encoding="utf-8"))
    assert doc["shapes"][0]["label"] == "scratch"


@pytest.mark.unit
def test_statistics_survives_corrupt_json(labelme_dir):
    from labeling.batch_tools import label_data_statistics

    _write_labelme(labelme_dir / "ok.json")
    (labelme_dir / "broken.json").write_text("not json", encoding="utf-8")

    stats = label_data_statistics(str(labelme_dir))
    assert stats == {"crack": 1}


# ============================== L2：save_labelme 原子性 ============================== #


@pytest.mark.unit
def test_save_labelme_atomic_roundtrip(tmp_path):
    """L2：保存走原子写单源——内容往返一致，且落盘是合法 JSON。"""
    from labeling.base import AnnotationMode, Shape
    from labeling.io_labelme import load_labelme_shapes, save_labelme

    shapes = [Shape(mode=AnnotationMode.RECTANGLE,
                    points=((1.0, 2.0), (30.0, 40.0)),
                    label="defect")]
    target = tmp_path / "ann.json"
    save_labelme(str(target), shapes, "img.png", 100, 100)

    back = load_labelme_shapes(str(target))
    assert len(back) == 1 and back[0].label == "defect"
    # 原子写不残留 .tmp
    assert not list(tmp_path.glob("*.tmp"))


# ============================== L5：撤销栈上限 ============================== #


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.mark.unit
def test_undo_stack_bounded(qapp):
    """L5：撤销栈 deque(maxlen=100)——超限丢最旧，内存有界。"""
    from collections import deque

    from labeling.canvas import AnnotationCanvas

    canvas = AnnotationCanvas()
    assert isinstance(canvas._undo_stack, deque)
    assert canvas._undo_stack.maxlen == 100, "撤销栈必须有界"


# ============================== L4：多边形点击闭合 ============================== #


@pytest.mark.unit
def test_polygon_click_close_requests_commit():
    """L4：点击首点附近 → close_requested=True（controller 据此立即提交）。"""
    from labeling.modes.polygon import PolygonLabeler

    labeler = PolygonLabeler("defect")
    # 三个顶点后点击首点附近
    labeler.on_press((10.0, 10.0))
    labeler.on_press((50.0, 10.0))
    labeler.on_press((50.0, 50.0))
    labeler.on_press((11.0, 11.0))  # 距首点 ~1.4px < 8px 阈值

    assert labeler.close_requested is True, "命中闭合区必须置请求标志"
    assert len(labeler.points) == 3, "闭合点击不追加顶点"

    # commit 后标志复位
    shape = labeler.commit()
    assert shape is not None
    assert labeler.close_requested is False


# ============================== L6：AUTO commit 上限 ============================== #


@pytest.mark.unit
def test_handle_commit_bounded_against_infinite_queue():
    """L6：无限回填的假 labeler 不再死循环（上限迭代后退出）。"""
    from labeling.base import AnnotationMode, Shape
    from labeling.controller import AnnotationController

    class _InfiniteLabeler:
        """首次 commit 返回 None（进入 AUTO 队列分支），此后永不 None
        （模拟异步回填）的病态实现。"""
        label = "x"
        _first = True

        def commit(self):
            if self._first:
                self._first = False
                return None
            return Shape(mode=AnnotationMode.RECTANGLE,
                         points=((0, 0), (1, 1)), label="x")

        @property
        def pending_count(self):
            return 10  # 上限生效依据

    ctrl = AnnotationController.__new__(AnnotationController)
    ctrl._labeler = _InfiniteLabeler()
    committed = []
    ctrl._commit_shape = lambda s: committed.append(s)
    ctrl._canvas = None

    ctrl.handle_commit()
    assert len(committed) == 10, "必须按 pending_count 上限截断而非无限循环"


# ============================== E1：seg/abdet 显式拒绝 ============================== #


@pytest.mark.unit
def test_evaluate_seg_dict_form_rejected_with_clear_error():
    """E1：dict 形态（eval_flow 供给形态）→ ValueError 指明不支持，
    不再 TypeError 逃逸。"""
    from evaluation.metrics_supervised import evaluate_supervised

    with pytest.raises(ValueError, match="seg"):
        evaluate_supervised("seg", [{"boxes": []}], [{"boxes": []}])


@pytest.mark.unit
def test_evaluate_abdet_dict_form_rejected():
    from evaluation.metrics_supervised import evaluate_supervised

    with pytest.raises(ValueError, match="abdet"):
        evaluate_supervised("abdet", [{"s": 1}], [1])


# ============================== E10/E11：AUROC NaN 与并列分数 ============================== #


@pytest.mark.unit
def test_auroc_insufficient_returns_nan():
    """E10：样本不足 → NaN（走 N/A 显示），不再误读为 0（模型反向）。"""
    from evaluation.metrics_supervised import abdet_auroc

    v = abdet_auroc([0.9, 0.8], [1, 1])  # 单标签
    assert v != v, "单标签必须 NaN（!= 自身判 NaN）"


@pytest.mark.unit
def test_auroc_tie_scores_order_independent():
    """E11：并列分数下结果与输入顺序无关（平均 TPR 组处理）。

    构造：同一样本集两种排列（分数与标签成对重排），含大量并列 0.5。
    """
    from evaluation.metrics_supervised import abdet_auroc

    scores_a = [0.9, 0.5, 0.5, 0.5, 0.1]
    labels_a = [1, 1, 0, 0, 0]
    # 成对重排（分数-标签绑定关系不变，仅顺序不同）
    order = [4, 2, 0, 3, 1]
    scores_b = [scores_a[i] for i in order]
    labels_b = [labels_a[i] for i in order]

    a = abdet_auroc(scores_a, labels_a)
    b = abdet_auroc(scores_b, labels_b)
    assert a == pytest.approx(b), "并列分数不得使结果依赖输入序"
    assert 0.0 <= a <= 1.0


# ============================== E2/E3：回退计数与坏 JSON 容错 ============================== #


@pytest.mark.unit
def test_eval_flow_skips_corrupt_json_and_warns(tmp_path):
    """E3：坏 JSON 跳过不崩 + E2 回退口径经 on_warn 汇报。"""
    from evaluation.eval_flow import run_supervised_eval

    _write_labelme(tmp_path / "good.json")
    (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")

    warns = []
    rows = run_supervised_eval(
        model="nonexistent.pt", gt_dir=str(tmp_path), task_key="det",
        on_warn=warns.append,
    )
    assert rows, "好文件仍产出指标行"
    assert any("损坏" in w or "回退" in w for w in warns), \
        f"坏文件/回退必须显式汇报: {warns}"


# ============================== X7：int8 路径返回 ============================== #


@pytest.mark.unit
def test_try_quantize_returns_int8_path(tmp_path, monkeypatch):
    """X7：int8 量化返回 .int8.onnx 实际产物路径。"""
    from exporter.supervised_exporter import SupervisedExporter

    fake_onnx = tmp_path / "model.onnx"
    fake_onnx.write_bytes(b"fake-onnx")

    from pathlib import Path as P

    def fake_dynamic(src, dst, **kw):
        P(dst).write_bytes(b"fake-int8")
        return None

    import onnxruntime.quantization as q
    monkeypatch.setattr(q, "quantize_dynamic", fake_dynamic)

    exp = SupervisedExporter()
    # 直接测内层：静态分支 ImportError 会回退动态
    out = exp._try_quantize(fake_onnx, "int8", (1, 3, 64, 64))
    assert out is not None and str(out).endswith(".int8.onnx"), \
        f"int8 必须返回实际产物路径: {out}"


# ============================== E20：FID 非负 ============================== #


@pytest.mark.unit
def test_fid_clamped_nonnegative(monkeypatch):
    """E20：trace 数值微负 → 返回值钳位为 0（不显示 -0.00xx）。

    公式级验证（不触发 InceptionV3 特征提取/权重下载——完整路径
    需网络与 torch 前向，CI 不依赖）：复现 fid_score 计算段，注入
    使 trace 微负的 _sqrtm 返回。
    """
    from evaluation import generative_metrics as gm

    # 特征/图像加载全部打桩（避免文件 IO 与 InceptionV3 权重下载）
    feats = np.eye(3, dtype=np.float64)

    monkeypatch.setattr(gm, "_to_numpy", lambda imgs: np.zeros((1, 4, 4, 3)))
    monkeypatch.setattr(gm, "_extract_features", lambda arr, *a, **k: feats)

    def fake_sqrtm(mat, eps=1e-6):
        # trace(Σg+Σr-2·sqrtm) = trace(2I - 2·1.0000000001·I) 微负
        return np.eye(mat.shape[0]) * 1.0000000001, False

    monkeypatch.setattr(gm, "_sqrtm", fake_sqrtm)

    val = gm.fid_score(["fake.png"], ["fake2.png"])
    assert val == 0.0, f"微负 FID 必须钳位为 0: {val}"
