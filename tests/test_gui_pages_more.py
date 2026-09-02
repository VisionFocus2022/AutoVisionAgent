"""gui 各页行为测试（W7-T2 覆盖棘轮推进：settings/predict/login/data_manage workers）。

选取规则：纯逻辑或离屏可驱动的高价值路径——设置保存与重置、推理结果表
与 CSV 导出（含公式注入防护）、登录离线/错误密码路径、数据管理 worker
纯函数全测。
"""
from __future__ import annotations

import csv
import json
import os
import threading

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeThread:
    created = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}
        FakeThread.created.append(self)

    def start(self):
        if self._t:
            self._t(*self._a, **self._k)


@pytest.fixture
def fake_threads(monkeypatch):
    FakeThread.created = []
    monkeypatch.setattr(threading, "Thread", FakeThread)
    return FakeThread


# ============================== settings 页 ============================== #
@pytest.mark.unit
def test_settings_save_writes_json_and_applies(qapp, tmp_path, monkeypatch):
    from gui.pages.settings import page as settings_mod

    monkeypatch.setattr(settings_mod, "_CONFIG_DIR", tmp_path)
    page = settings_mod.SettingsPage()
    page._theme_combo.setCurrentIndex(2)   # auto
    page._lang_combo.setCurrentIndex(1)    # en_US
    page._workspace_edit.setText(str(tmp_path / "ws"))

    page._save()

    saved = json.loads((tmp_path / "user_settings.json").read_text(encoding="utf-8"))
    assert saved["theme"] == "auto"
    assert saved["language"] == "en_US"
    assert saved["workspace"].endswith("ws")

    from gui.core.i18n import current_language, set_language

    assert current_language() == "en_US"
    set_language("ch_CN")  # 恢复全局态，避免污染其他测试


@pytest.mark.unit
def test_settings_reset_restores_defaults(qapp, tmp_path, monkeypatch):
    from gui.pages.settings import page as settings_mod

    monkeypatch.setattr(settings_mod, "_CONFIG_DIR", tmp_path)
    page = settings_mod.SettingsPage()
    page._theme_combo.setCurrentIndex(2)
    page._lang_combo.setCurrentIndex(1)
    page._reset()
    assert page._theme_combo.currentIndex() == 0
    assert page._lang_combo.currentIndex() == 0


# ============================== predict 页 ============================== #
@pytest.mark.unit
def test_predict_add_result_row_and_stats(qapp):
    from core.interfaces_supervised import DetectionResult, TaskType
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    r = DetectionResult(
        task=TaskType.DET, score=0.8, boxes=np.ones((2, 4)),
        labels=("crack",), scores=(0.8, 0.7),
    )
    page._add_result_row("a.png", r)
    page._add_result_row("b.png", r)
    assert page.table.rowCount() == 2
    assert page.table.item(0, 1).text() == "crack"
    assert page.table.item(0, 2).text() == "0.8000"
    assert page.table.item(0, 3).text().startswith("2")  # "2 boxes"


@pytest.mark.unit
def test_predict_export_csv_sanitizes_formula(qapp, tmp_path, monkeypatch):
    """CSV 公式注入防护：= 开头单元格加 ' 前缀（安全契约）。"""
    from gui.pages.predict import page as pred_mod

    page = pred_mod.PredictPage()
    out = tmp_path / "r.csv"
    monkeypatch.setattr(pred_mod, "pick_save_file", lambda *a, **k: str(out))
    page._results = [
        {"file": "=cmd|' /C calc'!A0", "task": "det", "score": 0.5,
         "labels": ["=HYPERLINK(\"x\")"], "boxes": []},
    ]
    page._export_csv()
    rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[1][0].startswith("'=cmd")
    assert rows[1][3].startswith("'=HYPERLINK")


@pytest.mark.unit
def test_predict_export_csv_empty_warns(qapp):
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append(t))
    page._results = []
    page._export_csv()
    assert any("无数据" in t for t in msgs)


# ============================== login 页 ============================== #
def _make_users_db(tmp_path, username="engineer", password="pw123456"):
    from core.auth import hash_password

    pw_hash, salt_hex, iterations = hash_password(password)
    (tmp_path / "users.json").write_text(
        json.dumps(
            {
                username: {
                    "password_hash": pw_hash,
                    "salt": salt_hex,
                    "iterations": iterations,
                    "role": "工程师",
                    "must_change": False,
                    "locked": False,
                }
            }
        ),
        encoding="utf-8",
    )
    return username, password


@pytest.mark.unit
def test_login_wrong_password_warns(qapp, tmp_path, monkeypatch):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    user, pw = _make_users_db(tmp_path)
    page = login_mod.LoginPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append(t))

    page._user_edit.setText(user)
    page._pass_edit.setText("wrong-password")
    page._do_login()
    assert any("密码错误" in t or "失败" in t for t in msgs)


@pytest.mark.unit
def test_login_offline_with_license(qapp, tmp_path, monkeypatch):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    (tmp_path / "license.key").write_text("", encoding="utf-8")
    page = login_mod.LoginPage()
    logged = []
    page.login_success.connect(lambda u, r: logged.append((u, r)))

    page._do_offline()
    assert logged == [("offline", "operator")]  # W18 枚举；W39 反转：离线=operator 受限会话


@pytest.mark.unit
def test_login_offline_without_license_declined(qapp, tmp_path, monkeypatch):
    """无 license.key：确认框选'否'不得进入（P2-11 行为锚定）。"""
    from PySide6.QtWidgets import QMessageBox

    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.No)
    )
    page = login_mod.LoginPage()
    logged = []
    page.login_success.connect(lambda u, r: logged.append((u, r)))

    page._do_offline()
    assert logged == []  # 拒绝后不进入


# ============================== data_manage workers（纯函数） ============================== #
def _labelme(path, image_name, w, h, shapes):
    path.write_text(
        json.dumps({"version": "5.4.3", "imagePath": image_name,
                    "imageHeight": h, "imageWidth": w, "shapes": shapes}),
        encoding="utf-8",
    )


def _png(path, w=64, h=48):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


@pytest.fixture
def ann_fixture(tmp_path):
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    _png(img_dir / "a.png")
    _png(img_dir / "b.png")
    _labelme(
        ann_dir / "a.json", "a.png", 64, 48,
        [{"label": "crack", "shape_type": "rectangle",
          "points": [[4, 4], [20, 16]], "group_id": None, "flags": {}}],
    )
    _labelme(
        ann_dir / "b.json", "b.png", 64, 48,
        [{"label": "old", "shape_type": "rectangle",
          "points": [[2, 2], [10, 10]], "group_id": None, "flags": {}}],
    )
    return img_dir, ann_dir


@pytest.mark.unit
def test_workers_split_move_mode(ann_fixture, tmp_path):
    from gui.pages.data_manage import workers

    img_dir, _ = ann_fixture
    # move 模式：原文件被移走，子目录齐全
    n = workers.split_dataset(str(img_dir), 1.0, 0.0, 0.0, "move")
    assert n[0] == 2
    assert not (img_dir / "a.png").exists()
    assert (img_dir / "train" / "a.png").exists()


@pytest.mark.unit
def test_workers_split_list_mode(ann_fixture):
    from gui.pages.data_manage import workers

    img_dir, _ = ann_fixture
    n = workers.split_dataset(str(img_dir), 0.5, 0.5, 0.0, "list")
    assert sum(n) == 2
    lst = (img_dir / "train" / "file_list.txt").read_text(encoding="utf-8")
    assert ".png" in lst
    # list 模式不搬文件
    assert (img_dir / "a.png").exists() and (img_dir / "b.png").exists()


@pytest.mark.unit
def test_workers_replace_and_delete_and_stats(ann_fixture):
    from gui.pages.data_manage import workers

    _, ann_dir = ann_fixture
    assert workers.replace_labels(str(ann_dir), "old", "new") == 1
    doc = json.loads((ann_dir / "b.json").read_text(encoding="utf-8"))
    assert doc["shapes"][0]["label"] == "new"

    stats = workers.label_statistics(str(ann_dir))
    assert stats.get("crack", {}).get("count") == 1
    assert stats.get("new", {}).get("count") == 1

    assert workers.delete_labels(str(ann_dir), ["new"]) == 1
    doc = json.loads((ann_dir / "b.json").read_text(encoding="utf-8"))
    assert doc["shapes"] == []


@pytest.mark.unit
def test_workers_flip_and_cut(ann_fixture):
    from gui.pages.data_manage import workers

    _, ann_dir = ann_fixture
    # 翻转：a.json 矩形 (4,4)-(20,16) 水平翻转于 w=64 → x2' = 64-4=60, x1'=64-20=44
    assert workers.flip_annotations(str(ann_dir), "horizontal") == 2
    doc = json.loads((ann_dir / "a.json").read_text(encoding="utf-8"))
    pts = doc["shapes"][0]["points"]
    assert sorted(p[0] for p in pts) == [44.0, 60.0]

    # 切割：32x32 瓦片（仅含形状的瓦片产出 json；两图各 1 个形状 → ≥2）
    total = workers.cut_annotations(str(ann_dir), 32, 32)
    assert total >= 2
    tiles = list((ann_dir / "tiles").glob("*.json"))
    assert len(tiles) == total
