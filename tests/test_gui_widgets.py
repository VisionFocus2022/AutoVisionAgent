"""gui 自定义组件测试（W8-T5 收尾：loss_chart 48% / file_dialog 27% 填平）。

loss_chart：多序列/自动配色/自动 epoch 递增/缩放重算/清空 + paintEvent
offscreen grab() 全路径（网格/曲线/轴/图例）。file_dialog：三个选择器经
QFileDialog 静态方法注入、最近目录记忆读写与容错（_LAST_DIR_FILE 重定向
到 tmp，避免污染用户主目录）。
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ============================== loss_chart ============================== #
@pytest.mark.unit
def test_loss_chart_series_and_auto_epoch(qapp):
    from gui.widgets.loss_chart import LossChartWidget

    w = LossChartWidget()
    w.resize(320, 240)
    w.set_title("train")
    assert w._title_label.text() == "train"

    w.add_series("loss", color="#ef4444")   # 显式配色
    w.add_series("acc")                     # 自动配色（索引 1 → 绿）
    assert set(w._series) == {"loss", "acc"}
    assert w._colors["acc"].name().lower() == "#22c55e"

    w.append("loss", 0.8)          # 首点 epoch=1
    w.append("loss", 0.5)          # 自动递增 epoch=2
    w.append("loss", 0.9, epoch=9)  # 显式 epoch
    assert list(w._series["loss"])[-1] == (9, 0.9)
    assert [pt[0] for pt in list(w._series["loss"])] == [1, 2, 9]

    w.append("newbie", 1.0)  # 未知序列自动补建
    assert "newbie" in w._series

    # 缩放重算：vals={0.8,0.5,0.9,1.0} → min 0.5/max 1.0 ±10% padding；x_max=9
    assert w._y_min == pytest.approx(0.45)
    assert w._y_max == pytest.approx(1.05)
    assert w._x_max == 9

    w.clear_all()
    assert (w._y_min, w._y_max, w._x_max) == (0.0, 1.0, 1)
    assert all(len(dq) == 0 for dq in w._series.values())


@pytest.mark.unit
def test_loss_chart_paint_offscreen(qapp):
    from gui.widgets.loss_chart import LossChartWidget

    w = LossChartWidget()
    w.resize(360, 260)
    assert not w.grab().isNull()  # 空数据

    w.add_series("loss")
    w.append("loss", 1.0)  # 单点：len<2 不画折线分支
    assert not w.grab().isNull()

    for i in range(4):
        w.append("loss", 1.0 - 0.2 * i)
    w.add_series("val_loss")
    for i in range(4):
        w.append("val_loss", 0.9 - 0.1 * i)
    assert not w.grab().isNull()  # 双曲线 + 网格 + 轴 + 图例

    # 常量序列：rng<1e-9 → 保护分支
    w2 = LossChartWidget()
    w2.resize(360, 260)
    w2.add_series("flat")
    w2.append("flat", 0.5)
    w2.append("flat", 0.5)
    assert not w2.grab().isNull()


# ============================== file_dialog ============================== #
@pytest.fixture
def fd_module(monkeypatch, tmp_path):
    from gui.widgets import file_dialog as fd

    monkeypatch.setattr(fd, "_LAST_DIR_FILE", str(tmp_path / "last_dir.json"))
    return fd


def _fake_dialog(monkeypatch, ret_value, calls):
    """按方法名注入 QFileDialog 静态方法替身，记录调用参数。"""
    from PySide6.QtWidgets import QFileDialog

    if isinstance(ret_value, tuple):
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a: (calls.append(("open", a)), ret_value)[1]),
        )
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName",
            staticmethod(lambda *a: (calls.append(("save", a)), ret_value)[1]),
        )
    else:
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory",
            staticmethod(lambda *a: (calls.append(("dir", a)), ret_value)[1]),
        )


@pytest.mark.unit
def test_pick_open_and_save_remember_last_dir(qapp, fd_module, monkeypatch, tmp_path):
    calls = []
    src = tmp_path / "weights.pt"
    src.write_bytes(b"x")
    _fake_dialog(monkeypatch, (str(src), ""), calls)

    # 无记忆 → start_dir 为空
    assert fd_module.pick_open_file(None, "选择模型权重", "*.pt") == str(src)
    kind, args = calls[-1]
    assert kind == "open" and args[2] == ""  # start_dir 空

    # 已记忆 → 以最近目录启动；选择后记忆更新为 dirname
    assert fd_module.pick_open_file(None, "选择模型权重", "*.pt") == str(src)
    assert calls[-1][1][2] == str(tmp_path)
    saved = json.loads((tmp_path / "last_dir.json").read_text("utf-8"))
    assert saved["last_open"] == str(tmp_path)  # 文件 → 记 dirname

    out = tmp_path / "sub" / "r.csv"
    out.parent.mkdir()
    out.write_bytes(b"")  # 已存在的保存目标 → 记 dirname 而非文件本身
    _fake_dialog(monkeypatch, (str(out), ""), calls)
    assert fd_module.pick_save_file(None, "导出CSV", "*.csv") == str(out)
    saved = json.loads((tmp_path / "last_dir.json").read_text("utf-8"))
    assert saved["last_save"].endswith("sub")


@pytest.mark.unit
def test_pick_directory_remembers_itself(qapp, fd_module, monkeypatch, tmp_path):
    calls = []
    d = tmp_path / "proj"
    d.mkdir()
    _fake_dialog(monkeypatch, str(d), calls)
    assert fd_module.pick_directory(None, "选择目录") == str(d)
    saved = json.loads((tmp_path / "last_dir.json").read_text("utf-8"))
    assert saved["last_dir"] == str(d)  # 目录 → 记自身

    # 取消（空串）→ 返回空且不写记忆
    before = (tmp_path / "last_dir.json").read_text("utf-8")
    _fake_dialog(monkeypatch, "", calls)
    assert fd_module.pick_directory(None, "选择目录") == ""
    assert (tmp_path / "last_dir.json").read_text("utf-8") == before


@pytest.mark.unit
def test_last_dir_io_tolerates_corrupt_and_missing(fd_module, tmp_path):
    assert fd_module._load_last_dir("nope") == ""  # 文件不存在

    bad = tmp_path / "last_dir.json"
    bad.write_text("{corrupt", encoding="utf-8")
    assert fd_module._load_last_dir("k") == ""  # 坏 JSON 容错

    fd_module._save_last_dir("")  # 空路径直接跳过
    assert fd_module._load_last_dir("k") == ""

    # 现状锚定：坏 JSON 时 _save_last_dir 整体被 except 吞（不写入），
    # 记忆功能静默失效直到文件被删除——恢复路径：删文件后保存生效。
    fd_module._save_last_dir(str(tmp_path / "a" / "b"))
    assert bad.read_text("utf-8") == "{corrupt"
    bad.unlink()
    fd_module._save_last_dir(str(tmp_path / "a" / "b"))
    assert fd_module._load_last_dir("last_dir").endswith("b")  # 不存在 → 记自身
