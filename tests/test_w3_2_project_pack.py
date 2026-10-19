"""W3-2 项目包 2.0 测试（PRD docs/prd-w3-2-project-pack.md）。

- AC-1 roundtrip：导出→新根导入→逐文件哈希相等
- AC-2 缺 manifest：非本项目包 zip → PackError 不落盘
- AC-3 损坏：zip 内篡改 → 校验失配列名、零落盘
- AC-4 碰撞：同名项目已存在 → 拒绝覆盖、原目录未触碰
- AC-5 空项目：files=0 可往返
- AC-6 页面：无选中提示/完成状态/失败复位
"""
from __future__ import annotations

import zipfile

import pytest

from project.pack import PackError, export_pack, import_pack

pytestmark = [pytest.mark.unit]


def _mk_project(root, name="demo_det_001"):
    proj = root / name
    for sub, fn, payload in (
        ("images", "a.png", b"png-bytes-aaa"),
        ("images", "b.png", b"png-bytes-bbb"),
        ("annotations", "a.json", b'{"shapes":[]}'),
        ("models", "m.pt", bytes(range(256))),
        ("configs", "c.json", b"{}"),
    ):
        d = proj / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / fn).write_bytes(payload)
    return proj


class TestAc1Roundtrip:
    def test_full_roundtrip_hashes_equal(self, tmp_path):
        proj = _mk_project(tmp_path)
        z = tmp_path / "p.zip"
        m = export_pack(str(proj), str(z))
        assert m["file_count"] == 5 and m["project_dirname"] == "demo_det_001"
        root2 = tmp_path / "root2"
        r = import_pack(str(z), str(root2))
        assert r["file_count"] == 5
        back = root2 / "demo_det_001"
        assert (back / "images/a.png").read_bytes() == b"png-bytes-aaa"
        assert (back / "models/m.pt").read_bytes() == bytes(range(256))
        assert (back / "annotations/a.json").read_bytes() == b'{"shapes":[]}'


class TestAc2MissingManifest:
    def test_plain_zip_rejected(self, tmp_path):
        z = tmp_path / "plain.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("x.txt", b"x")
        with pytest.raises(PackError, match="清单"):
            import_pack(str(z), str(tmp_path / "out"))
        assert not (tmp_path / "out").exists() or not any(
            (tmp_path / "out").iterdir()
        ), "拒绝时零落盘"


class TestAc3Corrupt:
    def _corrupt_zip(self, tmp_path):
        proj = _mk_project(tmp_path)
        z = tmp_path / "p.zip"
        export_pack(str(proj), str(z))
        # 重写一个 zip：manifest 保留、images/a.png 内容被篡改
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(z) as src, zipfile.ZipFile(
            bad, "w"
        ) as dst:
            for n in src.namelist():
                data = src.read(n)
                if n == "images/a.png":
                    data = b"TAMPERED!!"
                dst.writestr(n, data)
        return bad

    def test_checksum_mismatch_named_no_write(self, tmp_path):
        bad = self._corrupt_zip(tmp_path)
        out = tmp_path / "out"
        with pytest.raises(PackError, match="images/a.png"):
            import_pack(str(bad), str(out))
        assert not out.exists() or not any(out.iterdir()), "失配零落盘"


class TestAc4Collision:
    def test_refuse_overwrite(self, tmp_path):
        proj = _mk_project(tmp_path)
        z = tmp_path / "p.zip"
        export_pack(str(proj), str(z))
        root2 = tmp_path / "root2"
        import_pack(str(z), str(root2))  # 首次成功
        sentinel = (root2 / "demo_det_001" / "images" / "SENTINEL.txt")
        sentinel.write_bytes(b"keep-me")
        with pytest.raises(PackError, match="拒绝覆盖"):
            import_pack(str(z), str(root2))
        assert sentinel.read_bytes() == b"keep-me", "原目录未被触碰"


class TestAc5EmptyProject:
    def test_empty_roundtrip(self, tmp_path):
        proj = tmp_path / "empty_seg_001"
        proj.mkdir()
        z = tmp_path / "e.zip"
        m = export_pack(str(proj), str(z))
        assert m["file_count"] == 0
        r = import_pack(str(z), str(tmp_path / "root2"))
        assert r["file_count"] == 0
        assert (tmp_path / "root2" / "empty_seg_001").is_dir()


class TestAc6Page:
    @pytest.fixture(scope="class")
    def qapp(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def _page(self, qapp, monkeypatch, tmp_path):
        from gui.pages.project.page import ProjectPage

        monkeypatch.setattr(
            "gui.pages.project.page.resolve_base_root",
            lambda: str(tmp_path / "base"),
        )
        page = ProjectPage()
        msgs: list = []
        page.status_changed.connect(lambda t, a: msgs.append((t, a)))
        page._msgs = msgs
        return page

    def test_export_requires_selection(self, qapp, monkeypatch, tmp_path):
        page = self._page(qapp, monkeypatch, tmp_path)
        page._export_pack()
        assert any("请先选择项目" in t for t, _ in page._msgs)

    def test_pack_done_and_failed_slots(self, qapp, monkeypatch, tmp_path):
        page = self._page(qapp, monkeypatch, tmp_path)
        page._pack_done_slot("5")
        assert page.btn_pack_export.isEnabled()
        assert any("项目包完成" in t and "5" in a for t, a in page._msgs)
        page._pack_failed_slot("拒绝覆盖: x")
        assert any("项目包失败" in t for t, _ in page._msgs)
