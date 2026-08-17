"""batch_tools JSON 写盘原子化测试（W15-A1 / 架构审查 v2 P2-2，RED 先行）。

背景：labeling/batch_tools.py 的标注 JSON 直写是 truncate-then-write
（open(path, "w") 先截断再写）——批量标注进行中进程退出或写盘中途失败，
目标 JSON 被截断且旧内容已丢（v2 文档记载 :102-103/:202-203/:240，
现场复核实为四处：batch_replace_label :140-141 为文档漏记）。

契约（三重断言）：
- 机制：所有标注 JSON 落盘必须经 os.replace(tmp, target) 原子替换；
  tmp 与目标同目录（同盘才原子）、名称非目标本身、以 .tmp 结尾；
- 故障注入：os.replace 抛 OSError → 异常照常上抛（类型不变），
  目标文件旧内容逐字节完好，且目录无 .tmp 残留；
- 语义保持：成功路径写入内容与直写版逐字节一致
  （utf-8 编码 / ensure_ascii=False / indent=2）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import labeling.batch_tools as bt


def _labelme_doc(label: str = "defect") -> dict:
    """最小合法 LabelMe 标注字典。"""
    return {
        "version": "5.4.3",
        "flags": {},
        "shapes": [
            {
                "label": label,
                "points": [[10.0, 10.0], [90.0, 90.0]],
                "group_id": None,
                "shape_type": "rectangle",
            }
        ],
        "imagePath": "img.jpg",
        "imageData": None,
        "imageHeight": 100,
        "imageWidth": 100,
    }


def _write_labelme(path: Path, label: str = "defect") -> str:
    """写一个最小合法 LabelMe JSON，返回其序列化文本。"""
    text = json.dumps(_labelme_doc(label), ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    return text


class _ReplaceSpy:
    """记录 os.replace 调用并转发到真实实现。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._real = os.replace

    def __call__(self, src: str, dst: str) -> None:
        self.calls.append((src, dst))
        self._real(src, dst)


def _assert_atomic_replaces(spy: _ReplaceSpy, expected_dsts: set[str]) -> None:
    """机制断言：replace 被调、源为同目录 .tmp 临时文件、目标吻合。"""
    assert spy.calls, "os.replace 未被调用——JSON 仍为直写（非原子）"
    for src, dst in spy.calls:
        assert dst in expected_dsts, f"replace 目标异常: {dst}"
        assert src != dst, "replace 源与目标相同（原地写，非原子）"
        assert os.path.basename(src).endswith(".tmp"), f"源非 .tmp: {src}"
        assert os.path.dirname(src) == os.path.dirname(dst), (
            "tmp 与目标不同目录——跨盘 os.replace 不原子"
        )


# ---------------------------------------------------------------------------
# cut_labelme_json
# ---------------------------------------------------------------------------


def test_cut_labelme_json_writes_via_os_replace(tmp_path, monkeypatch):
    """机制：瓦片 JSON 落盘走 tmp + os.replace。"""
    src = tmp_path / "big.json"
    _write_labelme(src)
    out_dir = tmp_path / "tiles"

    spy = _ReplaceSpy()
    monkeypatch.setattr(bt.os, "replace", spy)

    results = bt.cut_labelme_json(str(src), 100, 100, str(out_dir))
    assert len(results) == 1

    _assert_atomic_replaces(spy, {str(out_dir / "big_0_0.json")})
    tile_doc = json.loads(
        Path(results[0]).read_text(encoding="utf-8")
    )
    assert tile_doc["shapes"][0]["points"] == [[10.0, 10.0], [90.0, 90.0]]


def test_cut_labelme_json_replace_failure_keeps_existing_tile(
    tmp_path, monkeypatch
):
    """故障注入：replace 抛 OSError → 旧瓦片完好、无 tmp 残留。"""
    src = tmp_path / "big.json"
    _write_labelme(src)
    out_dir = tmp_path / "tiles"
    out_dir.mkdir()
    old_tile = out_dir / "big_0_0.json"
    old_tile.write_text('{"OLD": true}', encoding="utf-8")

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full (injected)")

    monkeypatch.setattr(bt.os, "replace", boom)

    with pytest.raises(OSError):
        bt.cut_labelme_json(str(src), 100, 100, str(out_dir))

    assert old_tile.read_text(encoding="utf-8") == '{"OLD": true}'
    assert list(out_dir.glob("*.tmp")) == [], "replace 失败后残留 .tmp 文件"


# ---------------------------------------------------------------------------
# batch_replace_label
# ---------------------------------------------------------------------------


def test_batch_replace_label_writes_via_os_replace(tmp_path, monkeypatch):
    """机制+语义：替换落盘走 tmp+replace，内容与直写版逐字节一致。"""
    target = tmp_path / "a.json"
    _write_labelme(target)
    doc = _labelme_doc()
    doc["shapes"][0]["label"] = "ok"
    expected_text = json.dumps(doc, ensure_ascii=False, indent=2)

    spy = _ReplaceSpy()
    monkeypatch.setattr(bt.os, "replace", spy)

    count = bt.batch_replace_label(str(tmp_path), "defect", "ok")
    assert count == 1

    _assert_atomic_replaces(spy, {str(target)})
    assert target.read_text(encoding="utf-8") == expected_text


def test_batch_replace_label_replace_failure_keeps_original(
    tmp_path, monkeypatch
):
    """故障注入：replace 抛 OSError → 原文件完好、异常上抛、无 tmp 残留。"""
    target = tmp_path / "a.json"
    original_text = _write_labelme(target)

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full (injected)")

    monkeypatch.setattr(bt.os, "replace", boom)

    with pytest.raises(OSError):
        bt.batch_replace_label(str(tmp_path), "defect", "ok")

    assert target.read_text(encoding="utf-8") == original_text
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# batch_delete_labels
# ---------------------------------------------------------------------------


def test_batch_delete_labels_writes_via_os_replace(tmp_path, monkeypatch):
    """机制：删除标签后落盘走 tmp + os.replace。"""
    target = tmp_path / "a.json"
    _write_labelme(target)

    spy = _ReplaceSpy()
    monkeypatch.setattr(bt.os, "replace", spy)

    count = bt.batch_delete_labels(str(tmp_path), ["defect"])
    assert count == 1

    _assert_atomic_replaces(spy, {str(target)})
    assert json.loads(target.read_text(encoding="utf-8"))["shapes"] == []


def test_batch_delete_labels_replace_failure_keeps_original(
    tmp_path, monkeypatch
):
    """故障注入：replace 抛 OSError → 原文件完好、无 tmp 残留。"""
    target = tmp_path / "a.json"
    original_text = _write_labelme(target)

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full (injected)")

    monkeypatch.setattr(bt.os, "replace", boom)

    with pytest.raises(OSError):
        bt.batch_delete_labels(str(tmp_path), ["defect"])

    assert target.read_text(encoding="utf-8") == original_text
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# flip_image_annotation
# ---------------------------------------------------------------------------


def test_flip_image_annotation_writes_via_os_replace(tmp_path, monkeypatch):
    """机制+语义：翻转落盘走 tmp+replace，内容与直写版逐字节一致。"""
    target = tmp_path / "a.json"
    _write_labelme(target)
    doc = _labelme_doc()
    for s in doc["shapes"]:
        s["points"] = [
            [100 - p[0], p[1]] for p in s["points"]
        ]
    expected_text = json.dumps(doc, ensure_ascii=False, indent=2)

    spy = _ReplaceSpy()
    monkeypatch.setattr(bt.os, "replace", spy)

    assert bt.flip_image_annotation(str(target), 100, "horizontal") is True

    _assert_atomic_replaces(spy, {str(target)})
    assert target.read_text(encoding="utf-8") == expected_text


def test_flip_image_annotation_replace_failure_keeps_original(
    tmp_path, monkeypatch
):
    """故障注入：replace 抛 OSError → 原文件完好、无 tmp 残留。"""
    target = tmp_path / "a.json"
    original_text = _write_labelme(target)

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full (injected)")

    monkeypatch.setattr(bt.os, "replace", boom)

    with pytest.raises(OSError):
        bt.flip_image_annotation(str(target), 100, "horizontal")

    assert target.read_text(encoding="utf-8") == original_text
    assert list(tmp_path.glob("*.tmp")) == []
