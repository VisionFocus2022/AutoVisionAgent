"""evaluation/eval_flow.py 纯函数直测（W12-R2：eval 页业务流抽层）。

无 Qt 依赖：小合成数据 + 替身引擎走通主路径 / 空数据路径 / 引擎回退路径 /
生成式 FID·LPIPS 路径 / 任务分发。对照 data_manage/workers.py 纯函数范式。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from evaluation.eval_flow import (
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
    """替身引擎：infer 返回自身（携带 boxes/score）。"""

    def __init__(self, boxes=None, score=0.9):
        self.calls = []
        self.boxes = np.array(boxes if boxes is not None else [[4.0, 4.0, 20.0, 16.0]])
        self.score = score

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
