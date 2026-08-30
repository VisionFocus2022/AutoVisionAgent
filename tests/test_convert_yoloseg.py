"""convert_labelme_to_yoloseg 纯函数单测（W50 · TDD）。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "conv", Path(__file__).resolve().parents[1] / "scripts" / "convert_labelme_to_yoloseg.py"
)
conv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(conv)


class TestPolygonToYoloLine:
    def test_normalized_output(self):
        line = conv.polygon_to_yolo_line(
            [[100, 100], [200, 100], [200, 200], [100, 200]], 1600, 1600
        )
        parts = line.split()
        assert parts[0] == "0"
        vals = [float(v) for v in parts[1:]]
        assert len(vals) == 8
        assert all(0.0 <= v <= 1.0 for v in vals)
        assert abs(vals[0] - 100 / 1600) < 1e-5
        assert abs(vals[-1] - 200 / 1600) < 1e-5

    def test_clamp_out_of_bounds(self):
        line = conv.polygon_to_yolo_line(
            [[-5, 0], [1700, 0], [800, 1700]], 1600, 1600
        )
        vals = [float(v) for v in line.split()[1:]]
        assert min(vals) == 0.0 and max(vals) == 1.0

    def test_too_few_points_none(self):
        assert conv.polygon_to_yolo_line([[0, 0], [10, 10]], 100, 100) is None


class TestLabelmeToLines:
    def _write(self, tmp_path, shapes):
        p = tmp_path / "a.json"
        p.write_text(json.dumps({"shapes": shapes}), encoding="utf-8")
        return p

    def test_filters_non_defect(self, tmp_path):
        jp = self._write(tmp_path, [
            {"label": "YS", "shape_type": "polygon",
             "points": [[0, 0], [10, 0], [10, 10]]},
            {"label": "Z", "shape_type": "polygon",
             "points": [[0, 0], [5, 0], [5, 5]]},
            {"label": "YS", "shape_type": "rectangle",
             "points": [[0, 0], [9, 9]]},
        ])
        lines = conv.labelme_to_lines(jp, 100, 100)
        assert len(lines) == 1
        assert lines[0].startswith("0 ")

    def test_missing_file_empty(self, tmp_path):
        assert conv.labelme_to_lines(tmp_path / "nope.json", 10, 10) == []


class TestReadImageSize:
    def test_bmp_header(self, tmp_path):
        import struct

        p = tmp_path / "x.bmp"
        p.write_bytes(b"BM" + b"\x00" * 16 + struct.pack("<ii", 1600, 1600) + b"\x00" * 8)
        assert conv.read_image_size(p) == (1600, 1600)

    def test_not_bmp_none(self, tmp_path):
        p = tmp_path / "x.bmp"
        p.write_bytes(b"XX" + b"\x00" * 30)
        assert conv.read_image_size(p) is None


class TestDataYaml:
    def test_content(self, tmp_path):
        yp = conv.write_data_yaml(tmp_path)
        text = yp.read_text(encoding="utf-8")
        assert "nc: 1" in text
        assert "names: ['defect']" in text
        assert "train: images/train" in text and "val: images/val" in text
