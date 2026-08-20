"""evaluation/eval_flow.py 纯函数直测（W12-R2：eval 页业务流抽层）。

无 Qt 依赖：小合成数据 + 替身引擎走通主路径 / 空数据路径 / 引擎回退路径 /
生成式 FID·LPIPS 路径 / 任务分发。对照 data_manage/workers.py 纯函数范式。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from evaluation.eval_flow import (
    build_prediction,
    extract_gt,
    run_eval_task,
    run_generative_eval,
    run_supervised_eval,
    scan_images,
    scan_labelme_jsons,
)


def _labelme(path, name="a.png", points=((4, 4), (20, 16))):
    path.write_text(
        json.dumps({
            "imagePath": name,
            "shapes": [{
                "label": "crack",
                "shape_type": "rectangle",
                "points": [list(p) for p in points],
            }],
        }),
        encoding="utf-8",
    )


def _png_stub(path):
    path.write_bytes(b"\x89PNG stub")  # 仅需存在：替身引擎不真读图


class _StubEngine:
    """替身引擎：infer 返回自身（携带 boxes/score）。

    W17：可选逐框 scores/labels（模拟真实 det 引擎输出——det_yolo 返回
    scores=逐框置信度元组、labels=defect_N 字符串元组；零检出时三者全空）。
    """

    def __init__(self, boxes=None, score=0.9, scores=None, labels=None):
        self.calls = []
        self.boxes = np.array(boxes if boxes is not None else [[4.0, 4.0, 20.0, 16.0]])
        self.score = score
        self.scores = tuple(scores) if scores is not None else None
        self.labels = tuple(labels) if labels is not None else None

    def load(self, path, device="cpu"):
        pass

    def infer(self, img_path):
        self.calls.append(img_path)
        return self


# ============================== 扫描与解析 ============================== #
@pytest.mark.unit
def test_scan_labelme_jsons_filters_top_level_only(tmp_path):
    gt = tmp_path / "gt"
    sub = gt / "sub"
    sub.mkdir(parents=True)
    (gt / "a.json").write_text("{}", encoding="utf-8")
    (gt / "b.json").write_text("{}", encoding="utf-8")
    (gt / "img.png").write_bytes(b"x")
    (sub / "c.json").write_text("{}", encoding="utf-8")

    found = scan_labelme_jsons(str(gt))
    assert sorted(found) == [str(gt / "a.json"), str(gt / "b.json")]


@pytest.mark.unit
def test_scan_labelme_jsons_non_dir_returns_empty(tmp_path):
    assert scan_labelme_jsons(str(tmp_path / "nope")) == []


@pytest.mark.unit
def test_scan_images_recursive_lowercase_exts(tmp_path):
    root = tmp_path / "gen"
    (root / "d").mkdir(parents=True)
    (root / "top.JPG").write_bytes(b"x")
    (root / "d" / "a.png").write_bytes(b"x")
    (root / "d" / "note.txt").write_bytes(b"x")

    found = scan_images(str(root))
    assert sorted(found) == [
        str(root / "d" / "a.png"), str(root / "top.JPG")
    ]


@pytest.mark.unit
def test_extract_gt_rectangle_and_single_point_completion():
    ann = {"shapes": [
        {"shape_type": "rectangle", "points": [[4, 4], [20, 16]]},
        {"shape_type": "rectangle", "points": [[7, 8]]},   # 单点 → 补齐为点框
        {"shape_type": "polygon", "points": [[0, 0], [1, 1]]},  # 非矩形跳过
    ]}
    boxes, labels = extract_gt(ann)
    assert boxes == [[4, 4, 20, 16], [7, 8, 7, 8]]
    assert labels == [0, 0]


# ============================== 监督式主路径 ============================== #
@pytest.mark.unit
def test_run_supervised_eval_stub_engine_main_path(
    tmp_path, monkeypatch
):
    """替身引擎可用 → 逐张推理（相对 imagePath 补绝对路径）+ 进度上报。"""
    import models.supervised.registry as reg_mod

    gt = tmp_path / "gt"
    gt.mkdir()
    for i in range(6):  # 6 文件 → idx%5==0 在 0 与 5 触发两次进度
        _png_stub(gt / f"{i}.png")
        _labelme(gt / f"{i}.json", f"{i}.png")

    engine = _StubEngine()
    monkeypatch.setattr(reg_mod, "get_engine", lambda enum_val: engine)

    progress, warns = [], []
    rows = run_supervised_eval(
        "m.pt", str(gt), "det",
        on_progress=progress.append,
        on_warn=warns.append,
    )

    assert engine.calls == [str(gt / f"{i}.png") for i in range(6)]
    assert progress == [16, 100]  # int(1/6*100), int(6/6*100)
    assert warns == []
    assert [(m, v) for m, v, _ in rows] == [("class_0", "1.0000"), ("mAP", "1.0000")]


@pytest.mark.unit
def test_run_supervised_eval_engine_fallback_warns(tmp_path, monkeypatch):
    """引擎加载失败 → on_warn 一次（原 W1 文案）+ GT 自比较指标。"""
    import models.supervised.registry as reg_mod

    gt = tmp_path / "gt"
    gt.mkdir()
    _labelme(gt / "a.json", "a.png")

    def _boom(enum_val):
        raise RuntimeError("no engine")

    monkeypatch.setattr(reg_mod, "get_engine", _boom)

    warns = []
    rows = run_supervised_eval("m.pt", str(gt), "det", on_warn=warns.append)

    assert warns == ["评估引擎不可用，退化为 GT 自比较（指标仅供参考）"]
    assert [(m, v) for m, v, _ in rows] == [("class_0", "1.0000"), ("mAP", "1.0000")]


@pytest.mark.unit
def test_run_supervised_eval_empty_dir_na_row(tmp_path):
    gt = tmp_path / "gt"
    gt.mkdir()
    rows = run_supervised_eval("m.pt", str(gt), "det")
    assert rows == [("-", "N/A", "无标注数据")]


@pytest.mark.unit
def test_run_supervised_eval_translate_hook(tmp_path, monkeypatch):
    """translate 回调作用于行说明（页侧传 tr，此处验证钩子生效）。"""
    gt = tmp_path / "gt"
    gt.mkdir()
    rows = run_supervised_eval(
        "m.pt", str(gt), "det", translate=lambda s: f"[{s}]"
    )
    assert rows == [("-", "N/A", "[无标注数据]")]


# ============================== 生成式路径 ============================== #
@pytest.mark.unit
def test_run_generative_eval_fid_and_lpips(tmp_path, monkeypatch):
    import evaluation.generative_metrics as gm

    gt = tmp_path / "gt"
    gt.mkdir()
    _png_stub(gt / "r1.png")
    gen_file = tmp_path / "gen1.png"  # model 为单文件（非目录 → [model]）
    _png_stub(gen_file)

    seen = {}

    def _fid(g, r):
        seen["fid"] = (g, r)
        return 12.0

    def _lpips(g, r):
        seen["lpips"] = (g, r)
        return 0.25

    monkeypatch.setattr(gm, "fid_score", _fid)
    monkeypatch.setattr(gm, "perceptual_loss", _lpips)

    rows = run_generative_eval(str(gen_file), str(gt), "fid")
    assert rows == [("FID", "12.00", "生成质量")]
    assert seen["fid"] == ([str(gen_file)], [str(gt / "r1.png")])

    rows = run_generative_eval(str(gen_file), str(gt), "lpips")
    assert rows == [("LPIPS", "0.2500", "感知损失")]
    assert seen["lpips"] == ([str(gen_file)], [str(gt / "r1.png")])


@pytest.mark.unit
def test_run_generative_eval_empty_real_no_rows(tmp_path, monkeypatch):
    import evaluation.generative_metrics as gm

    called = []
    monkeypatch.setattr(gm, "fid_score", lambda g, r: called.append((g, r)) or 0.0)

    gt = tmp_path / "gt"  # 空目录 → real_imgs 空 → 不计算
    gt.mkdir()
    rows = run_generative_eval(str(tmp_path / "g.png"), str(gt), "fid")
    assert rows == []
    assert called == []


# ============== W18（v3 P3⑥）：FID/LPIPS 样本帽参数化 max_images ============== #
@pytest.mark.unit
def test_run_generative_eval_max_images_caps_both_sides(tmp_path, monkeypatch):
    """max_images=3：gen/real 各 5 张 → fid 两侧各收 ≤3 张。"""
    import evaluation.generative_metrics as gm

    gen = tmp_path / "gen"
    gt = tmp_path / "gt"
    gen.mkdir()
    gt.mkdir()
    for i in range(5):
        _png_stub(gen / f"g{i}.png")
        _png_stub(gt / f"r{i}.png")

    seen = {}
    monkeypatch.setattr(gm, "fid_score", lambda g, r: seen.update(fid=(g, r)) or 0.0)

    rows = run_generative_eval(str(gen), str(gt), "fid", max_images=3)

    g, r = seen["fid"]
    assert len(g) <= 3 and len(r) <= 3
    assert rows == [("FID", "0.00", "生成质量")]


@pytest.mark.unit
def test_run_generative_eval_default_cap_20(tmp_path, monkeypatch):
    """默认帽 20：两侧各放 25 张 stub → fid 各收 20 张（页侧不传行为不变）。"""
    import evaluation.generative_metrics as gm

    gen = tmp_path / "gen"
    gt = tmp_path / "gt"
    gen.mkdir()
    gt.mkdir()
    for i in range(25):
        _png_stub(gen / f"g{i}.png")
        _png_stub(gt / f"r{i}.png")

    seen = {}
    monkeypatch.setattr(gm, "fid_score", lambda g, r: seen.update(fid=(g, r)) or 0.0)

    run_generative_eval(str(gen), str(gt), "fid")

    g, r = seen["fid"]
    assert len(g) == 20 and len(r) == 20


@pytest.mark.unit
def test_run_eval_task_passes_max_images(tmp_path, monkeypatch):
    """run_eval_task 透传 max_images：fid 分支两侧各收 ≤3 张。"""
    import evaluation.generative_metrics as gm

    gen = tmp_path / "gen"
    gt = tmp_path / "gt"
    gen.mkdir()
    gt.mkdir()
    for i in range(5):
        _png_stub(gen / f"g{i}.png")
        _png_stub(gt / f"r{i}.png")

    seen = {}
    monkeypatch.setattr(gm, "fid_score", lambda g, r: seen.update(fid=(g, r)) or 0.0)

    run_eval_task(str(gen), str(gt), "fid", max_images=3)

    g, r = seen["fid"]
    assert len(g) <= 3 and len(r) <= 3


# ==================== W17（v3 P1-2）：M≠N 全组合与真实分数 ==================== #
def _stub_engine_by_monkeypatch(monkeypatch, engine):
    import models.supervised.registry as reg_mod
    monkeypatch.setattr(reg_mod, "get_engine", lambda enum_val: engine)


@pytest.mark.unit
def test_det_eval_more_preds_than_gt_uses_real_scores(tmp_path, monkeypatch):
    """M=1、N=2（多检出少标注，检测评估常态）：

    - 不再抛 IndexError（W17 前必崩：labels 截断后长度 1 ≠ boxes 长度 2）；
    - mAP 按引擎真实逐框置信度排序：FP 在数组前、TP 分数更高 → 排序后 TP
      先行 → AP=1.0（旧合成均匀分数下按插入序 FP 先行 → AP=0.5）。
    """
    gt = tmp_path / "gt"
    gt.mkdir()
    _png_stub(gt / "a.png")
    _labelme(gt / "a.json", "a.png")  # GT: (4,4)-(20,16) 1 框

    # 数组序 [FP(远处), TP(与 GT 重合)]，真实分数 [0.4, 0.9]
    engine = _StubEngine(
        boxes=[[400.0, 400.0, 420.0, 416.0], [4.0, 4.0, 20.0, 16.0]],
        score=0.0,
        scores=[0.4, 0.9],
        labels=["defect_1", "defect_0"],
    )
    _stub_engine_by_monkeypatch(monkeypatch, engine)

    rows = run_supervised_eval("m.pt", str(gt), "det")
    assert [(m, v) for m, v, _ in rows] == [("class_0", "1.0000"), ("mAP", "1.0000")]


@pytest.mark.unit
def test_det_eval_zero_preds_with_gt_no_crash(tmp_path, monkeypatch):
    """M=1、N=0（引擎零检出于有 GT 图——W17 前同样 IndexError）：

    预测三数组全空 → 该图不计预测，class_0/mAP 诚实为 0。
    """
    gt = tmp_path / "gt"
    gt.mkdir()
    _png_stub(gt / "a.png")
    _labelme(gt / "a.json", "a.png")

    engine = _StubEngine(boxes=[], score=0.9, scores=[], labels=[])
    _stub_engine_by_monkeypatch(monkeypatch, engine)

    rows = run_supervised_eval("m.pt", str(gt), "det")
    assert [(m, v) for m, v, _ in rows] == [("class_0", "0.0000"), ("mAP", "0.0000")]


@pytest.mark.unit
def test_det_eval_fewer_preds_than_gt_no_crash(tmp_path, monkeypatch):
    """M=2、N=1（少检出）：W17 前不崩但 labels 语义含混；修后单类对齐、TP 命中 → AP=1.0。"""
    gt = tmp_path / "gt"
    gt.mkdir()
    _png_stub(gt / "a.png")
    (gt / "a.json").write_text(json.dumps({
        "imagePath": "a.png",
        "shapes": [
            {"shape_type": "rectangle", "points": [[4, 4], [20, 16]]},
            {"shape_type": "rectangle", "points": [[100, 100], [120, 116]]},
        ],
    }), encoding="utf-8")

    engine = _StubEngine(boxes=[[4.0, 4.0, 20.0, 16.0]], score=0.9, scores=[0.9])
    _stub_engine_by_monkeypatch(monkeypatch, engine)

    rows = run_supervised_eval("m.pt", str(gt), "det")
    # 1 TP / 2 GT：recall 峰值 0.5 → 11 点插值 AP = 6/11 ≈ 0.5455
    assert [(m, v) for m, v, _ in rows] == [("class_0", "0.5455"), ("mAP", "0.5455")]


@pytest.mark.unit
def test_det_eval_equal_counts_anchor_unchanged(tmp_path, monkeypatch):
    """M==N 回归锚（AC-003）：M=N=2 全命中，有无逐框 scores 两个形态 AP 均 1.0000。"""
    gt = tmp_path / "gt"
    gt.mkdir()
    _png_stub(gt / "a.png")
    (gt / "a.json").write_text(json.dumps({
        "imagePath": "a.png",
        "shapes": [
            {"shape_type": "rectangle", "points": [[4, 4], [20, 16]]},
            {"shape_type": "rectangle", "points": [[100, 100], [120, 116]]},
        ],
    }), encoding="utf-8")

    two_boxes = [[4.0, 4.0, 20.0, 16.0], [100.0, 100.0, 120.0, 116.0]]

    engine_scores = _StubEngine(boxes=two_boxes, score=0.0, scores=[0.9, 0.4])
    _stub_engine_by_monkeypatch(monkeypatch, engine_scores)
    rows = run_supervised_eval("m.pt", str(gt), "det")
    assert [(m, v) for m, v, _ in rows] == [("class_0", "1.0000"), ("mAP", "1.0000")]

    engine_uniform = _StubEngine(boxes=two_boxes, score=0.9)  # 无 scores 属性
    _stub_engine_by_monkeypatch(monkeypatch, engine_uniform)
    rows = run_supervised_eval("m.pt", str(gt), "det")
    assert [(m, v) for m, v, _ in rows] == [("class_0", "1.0000"), ("mAP", "1.0000")]


@pytest.mark.unit
def test_det_map_length_mismatch_defense():
    """det_map 对长度失配的防御（W17）：labels/scores 与 boxes 不一致时按单类 0 对齐，
    不抛裸 IndexError（防未来调用方再次构造出失配输入）。"""
    from evaluation.metrics_supervised import det_map

    preds = [{
        "boxes": [[4.0, 4.0, 20.0, 16.0], [40.0, 40.0, 60.0, 56.0]],
        "scores": [0.9],                      # 长度 1 ≠ boxes 长度 2
        "labels": [0, 0, 0],                  # 长度 3 ≠ boxes 长度 2
    }]
    gts = [{"boxes": [[4.0, 4.0, 20.0, 16.0]], "labels": [0]}]
    result = det_map(preds, gts, iou_threshold=0.5)
    # precision 公式含 1e-9 防零分母 → AP ≈ 1.0（非精确值）
    assert result["mAP"] == pytest.approx(1.0)


# ============================== 任务分发 ============================== #
@pytest.mark.unit
def test_run_eval_task_dispatch_generative_vs_supervised(tmp_path, monkeypatch):
    """fid/lpips → 生成式分支（不扫 JSON）；det → 监督式分支。"""
    import models.supervised.registry as reg_mod

    monkeypatch.setattr(reg_mod, "get_engine", lambda enum_val: (_ for _ in ()).throw(RuntimeError()))
    gt = tmp_path / "gt"
    gt.mkdir()
    _labelme(gt / "a.json", "a.png")

    # det：监督式（引擎炸 → 回退 GT）
    rows = run_eval_task("m.pt", str(gt), "det")
    assert rows[0][0] == "class_0"

    # fid：生成式分支（无真实图 → 空行，不触引擎）
    rows = run_eval_task("m.pt", str(gt), "fid")
    assert rows == []


# ====== W23（v4 P3-3）：score/boxes 裸取防御（契约违反引擎不炸整场） ======
_MISSING = object()  # 哨兵：区分「未设属性」与「值=None」


class _DuckEngine:
    """契约违反替身：infer 返回自定义形态结果（缺 score / score=None / 缺 boxes）。

    真实引擎恒返回 DetectionResult（全字段带默认值）；本类模拟鸭子型/契约
    违反引擎——v4 对抗工程师实证 :119 result.boxes 与 :131 float(result.score)
    两处裸取的 AttributeError/TypeError 均逃出 except 元组击穿逐图回退韧性。
    """

    def __init__(self, boxes=_MISSING, score=_MISSING):
        if boxes is not _MISSING:
            self.boxes = np.array(boxes)
        if score is not _MISSING:
            self.score = score

    def infer(self, img_path):
        return self


@pytest.mark.unit
def test_build_prediction_engine_without_score_attr_fills_zero(tmp_path):
    """无 .score 属性（且无逐框 scores）：W23 前 AttributeError 逃出 except
    元组炸整场评估；修后 scores 回退 [0.0]*n_pred、三数组长度对齐不抛。"""
    _png_stub(tmp_path / "a.png")
    engine = _DuckEngine(boxes=[[4.0, 4.0, 20.0, 16.0], [40.0, 40.0, 60.0, 56.0]])

    pred = build_prediction(
        engine, {"imagePath": "a.png"}, str(tmp_path),
        [[4.0, 4.0, 20.0, 16.0]], [0],
    )

    assert pred["scores"] == [0.0, 0.0]
    assert pred["labels"] == [0, 0]
    assert len(pred["boxes"]) == 2


@pytest.mark.unit
def test_build_prediction_engine_score_none_fills_zero(tmp_path):
    """score=None：W23 前 float(None) TypeError 同族逃逸；修后回退 0.0。"""
    _png_stub(tmp_path / "a.png")
    engine = _DuckEngine(boxes=[[4.0, 4.0, 20.0, 16.0]], score=None)

    pred = build_prediction(
        engine, {"imagePath": "a.png"}, str(tmp_path),
        [[4.0, 4.0, 20.0, 16.0]], [0],
    )

    assert pred["scores"] == [0.0]


@pytest.mark.unit
def test_build_prediction_engine_without_boxes_attr_falls_back_gt(tmp_path):
    """无 .boxes 属性（W23 顺手统一）：与 boxes=None 同路——GT 框当预测 +
    引擎全局 score 均匀填充（非 _fallback_pred 的 0.5），不抛 AttributeError。"""
    _png_stub(tmp_path / "a.png")
    engine = _DuckEngine(score=0.9)  # 不设 boxes

    pred = build_prediction(
        engine, {"imagePath": "a.png"}, str(tmp_path),
        [[4.0, 4.0, 20.0, 16.0]], [0],
    )

    assert pred["boxes"] == [[4.0, 4.0, 20.0, 16.0]]  # GT 回退
    assert pred["scores"] == [0.9]                    # 全局 score 填充
    assert pred["labels"] == [0]
