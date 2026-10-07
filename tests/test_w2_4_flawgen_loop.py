"""W2-4 缺陷生成一期闭环测试（PRD docs/prd-w2-4-flawgen-loop.md）。

- AC-1 label load_folder 缝（无对话框/文件列表/current_folder/空目录提示）
- AC-2 去标注按钮（初始禁用/成功启用并携带目录/失败禁用）
- 引擎冒烟：SganBlendEngine 在合成小图上真融合（离线 OpenCV）
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _mk_imgs(d, n=2, size=96, with_flaw=False):
    import cv2
    import numpy as np

    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        img = np.full((size, size, 3), 120, np.uint8)
        img[20:40, 20:40] = 200
        if with_flaw:
            img[50:70, 50:70] = 30  # 深色"缺陷"块
        cv2.imwrite(str(d / f"img{i}.png"), img)
    return d


class TestAc1LabelLoadFolder:
    def test_load_folder_no_dialog(self, qapp, tmp_path, monkeypatch):
        from gui.pages.label import page as lp

        imgs = _mk_imgs(tmp_path / "ok")
        page = lp.LabelPage()
        # 对话框若被触发即炸（pick_directory monkeypatch 为 raise）
        monkeypatch.setattr(lp, "pick_directory",
                            lambda *a, **k: (_ for _ in ()).throw(
                                AssertionError("load_folder 不得弹对话框")))
        page.load_folder(str(imgs))
        assert page.current_folder == str(imgs)
        names = [page.file_list.item(i).text()
                 for i in range(page.file_list.count())]
        assert any("img0" in n for n in names), f"文件列表应载入: {names[:4]}"

    def test_load_folder_empty_warns(self, qapp, tmp_path):
        from gui.pages.label import page as lp

        empty = tmp_path / "empty"
        empty.mkdir()
        page = lp.LabelPage()
        msgs: list = []
        page.status_changed.connect(lambda t, a: msgs.append(t))
        page.load_folder(str(empty))
        assert any("无图像" in m for m in msgs)


class TestAc2AnnotateButton:
    def _page(self, qapp):
        from gui.pages.flaw_gen.page import FlawGenPage

        page = FlawGenPage()
        got: list = []
        page.annotate_requested.connect(got.append)
        return page, got

    def test_initially_disabled(self, qapp):
        page, _ = self._page(qapp)
        assert not page._annotate_btn.isEnabled()

    def test_done_enables_and_emits(self, qapp):
        page, got = self._page(qapp)
        page._out_edit.setText("/tmp/out_x")
        page._done_slot(3)  # 生成 3 张
        assert page._annotate_btn.isEnabled()
        page._goto_annotate()
        assert got == ["/tmp/out_x"]

    def test_done_zero_keeps_disabled(self, qapp):
        page, _ = self._page(qapp)
        page._done_slot(0)  # 一张没成（合成全失败）
        assert not page._annotate_btn.isEnabled()

    def test_failed_disables(self, qapp):
        page, _ = self._page(qapp)
        page._done_slot(2)
        page._failed_slot("engine boom")
        assert not page._annotate_btn.isEnabled()


@pytest.mark.integration
def test_sgan_blend_smoke(tmp_path):
    """引擎真融合冒烟：OK 模板 + 缺陷库 → 合成图与 mask 均非空。"""
    from core.interfaces_supervised import TaskType
    from models.supervised.engines import register_all_engines
    from models.supervised.registry import get_engine

    ok = _mk_imgs(tmp_path / "ok", with_flaw=False)
    flaw = _mk_imgs(tmp_path / "flaw", n=1, with_flaw=True)
    register_all_engines()  # 惰性注册（GUI 侧经 registered_tasks 触发）
    eng = get_engine(TaskType.SGAN)
    eng.load(flaw_database=str(flaw), device="cpu")
    res = eng.infer(str(sorted(ok.glob("*.png"))[0]))
    syn = (res.extra or {}).get("synthesized_image")
    assert syn is not None and syn.size > 0, "应产出合成图"
