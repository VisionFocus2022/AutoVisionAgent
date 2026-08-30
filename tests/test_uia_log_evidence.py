"""log_evidence 纯函数单测（W49 · 主门禁面，无 Qt/无 UIA）。

覆盖：打点偏移量隔离（旧内容不可见）/尾部增量/ERROR 行提取/正则轮询/
AUDIT 行解析（含 user 过滤）/双模式目录解析（env 注入）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "uia"))

from log_evidence import LogAnchor, resolve_app_log_dir, wait_audit_line  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_anchor_sees_only_increment(tmp_path):
    log = tmp_path / "autovision.log"
    _write(log, "old line\n")
    anchor = LogAnchor(log_dir=tmp_path)
    with open(log, "a", encoding="utf-8") as f:
        f.write("new line\n")
    tail = anchor.tail()
    assert "new line" in tail
    assert "old line" not in tail


def test_anchor_missing_file(tmp_path):
    anchor = LogAnchor(log_dir=tmp_path)
    assert anchor.tail() == ""
    assert anchor.error_lines() == []


def test_error_lines_filter(tmp_path):
    log = tmp_path / "autovision.log"
    _write(log, "")
    anchor = LogAnchor(log_dir=tmp_path)
    with open(log, "a", encoding="utf-8") as f:
        f.write("2026-08-29 10:00:00,000 - gui.pages - INFO - ok\n")
        f.write("2026-08-29 10:00:01,000 - gui.pages - ERROR - boom\n")
    errs = anchor.error_lines()
    assert len(errs) == 1 and "boom" in errs[0]


def test_wait_line_hit_and_timeout(tmp_path):
    log = tmp_path / "autovision.log"
    _write(log, "")
    anchor = LogAnchor(log_dir=tmp_path)
    assert anchor.wait_line(r"never", timeout=0.3) is None

    def _append_later():
        time.sleep(0.5)
        with open(log, "a", encoding="utf-8") as f:
            f.write("模型导出开始: model=x.pt\n")

    import threading

    t = threading.Thread(target=_append_later)
    t.start()
    m = anchor.wait_line(r"模型导出开始: model=(\S+)", timeout=5.0)
    t.join()
    assert m is not None and m.group(1) == "x.pt"


def test_wait_audit_line_parse_and_user_filter(tmp_path):
    log = tmp_path / "autovision.log"
    _write(log, "")
    anchor = LogAnchor(log_dir=tmp_path)
    with open(log, "a", encoding="utf-8") as f:
        f.write("2026-08-29 10:00:00,000 - core.audit_logger - INFO - "
                "AUDIT [2026-08-29T10:00:00] user=offline action=login\n")
        f.write("2026-08-29 10:00:05,000 - core.audit_logger - INFO - "
                "AUDIT [2026-08-29T10:00:05] user=admin action=login\n")
    m = wait_audit_line(anchor, "login", user="admin", timeout=1.0)
    assert m is not None and m.group("user") == "admin"
    assert wait_audit_line(anchor, "login", user="ghost", timeout=0.3) is None
    assert wait_audit_line(anchor, "export", timeout=0.3) is None


def test_resolve_app_log_dir_modes(monkeypatch, tmp_path):
    monkeypatch.setenv("AVA_UIA_SOURCE", "exe")
    assert resolve_app_log_dir().name == "logs"
    assert "dist" in str(resolve_app_log_dir())
    monkeypatch.setenv("AVA_UIA_SOURCE", "python")
    monkeypatch.setenv("AVA_LOG_DIR", str(tmp_path))
    assert resolve_app_log_dir() == tmp_path
