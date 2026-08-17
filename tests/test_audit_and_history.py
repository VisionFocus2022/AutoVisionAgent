"""core/audit_logger.py + core/detection_history.py 单元测试（R4-12）。

覆盖：AuditLogger 缓冲刷盘 + 查询过滤，
DetectionHistory 环形缓冲 + 持久化 + 统计。
"""
import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.mark.unit
class TestAuditLogger:
    """AuditLogger 功能测试。"""

    def test_singleton(self):
        """单例模式：多次实例化返回同一对象。"""
        from core.audit_logger import AuditLogger
        a1 = AuditLogger()
        a2 = AuditLogger()
        assert a1 is a2

    def test_log_and_flush(self, tmp_path):
        """记录日志 + 刷盘到文件。"""
        from core.audit_logger import AuditLogger, get_audit_logger
        # 单例模式下 __init__ 不重置 log_dir，需手动设置
        logger = AuditLogger(log_dir=tmp_path)
        logger._log_dir = tmp_path
        logger._buffer.clear()
        logger.log("test_action", user="tester", detail="hello")
        assert len(logger._buffer) == 1
        logger.flush()
        # 验证文件已写入
        files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(files) == 1
        with open(files[0], "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())
        assert entry["action"] == "test_action"
        assert entry["user"] == "tester"
        assert entry["details"]["detail"] == "hello"

    def test_query_by_action(self, tmp_path):
        """按操作类型查询。"""
        from core.audit_logger import AuditLogger
        logger = AuditLogger(log_dir=tmp_path)
        logger._log_dir = tmp_path
        logger._buffer.clear()
        logger.log("inference", user="u1")
        logger.log("train", user="u2")
        logger.log("inference", user="u3")
        logger.flush()
        results = logger.query(action="inference")
        assert len(results) == 2
        assert all(r["action"] == "inference" for r in results)

    def test_query_by_user(self, tmp_path):
        """按用户查询。"""
        from core.audit_logger import AuditLogger
        logger = AuditLogger(log_dir=tmp_path)
        logger._log_dir = tmp_path
        logger._buffer.clear()
        logger.log("inference", user="alice")
        logger.log("train", user="bob")
        logger.flush()
        results = logger.query(user="alice")
        assert len(results) == 1
        assert results[0]["user"] == "alice"


@pytest.mark.unit
class TestDetectionHistory:
    """DetectionHistory 功能测试。"""

    def test_singleton(self):
        """单例模式。"""
        from core.detection_history import DetectionHistory
        h1 = DetectionHistory()
        h2 = DetectionHistory()
        assert h1 is h2

    def test_add_and_query(self, tmp_path):
        """添加记录 + 内存查询。"""
        from core.detection_history import DetectionHistory
        history = DetectionHistory(history_dir=tmp_path, max_records=100)
        history.clear()
        history.add_record(
            task="det", image_path="/test.jpg",
            result_count=5, score_avg=0.9,
        )
        history.add_record(
            task="cls", image_path="/test2.jpg",
            result_count=1, score_avg=0.8,
        )
        results = history.query()
        assert len(results) == 2
        # 最新的在前
        assert results[0].image_path == "/test2.jpg"

    def test_query_by_task(self, tmp_path):
        """按任务过滤。"""
        from core.detection_history import DetectionHistory
        history = DetectionHistory(history_dir=tmp_path, max_records=100)
        history.clear()
        history.add_record(task="det", result_count=3)
        history.add_record(task="cls", result_count=1)
        history.add_record(task="det", result_count=2)
        results = history.query(task="det")
        assert len(results) == 2
        assert all(r.task == "det" for r in results)

    def test_stats(self, tmp_path):
        """统计摘要。"""
        from core.detection_history import DetectionHistory
        history = DetectionHistory(history_dir=tmp_path, max_records=100)
        history.clear()
        history.add_record(task="det", result_count=5, score_avg=0.9)
        history.add_record(task="det", result_count=3, score_avg=0.7)
        stats = history.stats()
        assert stats["total"] == 2
        assert stats["by_task"]["det"] == 2
        assert stats["total_detections"] == 8
        assert abs(stats["avg_score"] - 0.8) < 0.01

    def test_stats_empty(self, tmp_path):
        """空记录统计。"""
        from core.detection_history import DetectionHistory
        history = DetectionHistory(history_dir=tmp_path)
        history.clear()
        stats = history.stats()
        assert stats["total"] == 0

    def test_persist_to_file(self, tmp_path):
        """持久化写入文件。"""
        from core.detection_history import DetectionHistory
        history = DetectionHistory(history_dir=tmp_path, max_records=100)
        history._history_dir = tmp_path
        history.clear()
        history.add_record(task="det", image_path="/a.jpg", result_count=2)
        files = list(tmp_path.glob("history_*.jsonl"))
        assert len(files) == 1
        with open(files[0], "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())
        assert entry["task"] == "det"
        assert entry["image_path"] == "/a.jpg"


# ==================== W11-P1 追加：退出刷盘钩子 ==================== #
@pytest.mark.unit
class TestAuditLoggerAtExitFlush:
    """W11-P1：audit 单例首次创建时注册 atexit flush。

    背景：flush() 此前全仓零调用方（仅 shell.closeEvent 一处 GUI 退出路径），
    非正常退出/崩溃会丢最多 _buffer_max-1（99）条缓冲尾记录。
    """

    def test_singleton_creation_registers_atexit_flush(self, monkeypatch):
        """首次创建单例时经 atexit.register 注册 flush（RED：此前无任何注册）。"""
        import atexit

        from core.audit_logger import AuditLogger, get_audit_logger

        registered = []
        monkeypatch.setattr(
            atexit, "register", lambda func, *a, **k: registered.append(func)
        )
        # 重置单例，模拟进程内首次创建（monkeypatch 结束后自动还原）
        monkeypatch.setattr(AuditLogger, "_instance", None)

        audit = get_audit_logger()

        assert audit.flush in registered, (
            "audit 单例首次创建时应 atexit.register(self.flush)，"
            "否则进程退出/崩溃会丢最多 _buffer_max-1 条尾记录"
        )

    def test_flush_persists_buffer_and_clears(self, tmp_path):
        """flush 落盘且清空缓冲（atexit 钩子所依赖的行为）。"""
        from core.audit_logger import AuditLogger

        logger = AuditLogger(log_dir=tmp_path)
        # 单例模式：手动隔离写入目录（同既有测试做法）
        logger._log_dir = tmp_path
        logger._buffer.clear()
        logger.log("export", user="u1", path="a.onnx")
        logger.log("train", user="u2", epochs=3)
        assert len(logger._buffer) == 2

        logger.flush()

        # 缓冲清空
        assert logger._buffer == []
        # 两条均落盘
        files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["action"] == "export"
        assert json.loads(lines[1])["action"] == "train"


# ==================== W13-C3 追加：登录会话单例（core/session.py） ==================== #
@pytest.mark.unit
class TestSessionUser:
    """core/session.py：模块级会话单例（默认 "system"）。

    背景（v2 架构审查 P1-4）：全仓无当前用户持有者，audit 快捷函数
    user 默认恒 "system"，登录后审计无法归属到人。
    """

    def test_default_user_is_system(self):
        from core.session import get_current_user, reset_current_user

        reset_current_user()
        assert get_current_user() == "system"

    def test_set_and_get_roundtrip(self):
        from core.session import (
            get_current_user,
            reset_current_user,
            set_current_user,
        )

        try:
            set_current_user("engineer")
            assert get_current_user() == "engineer"
        finally:
            reset_current_user()

    def test_empty_user_falls_back_to_system(self):
        from core.session import (
            get_current_user,
            reset_current_user,
            set_current_user,
        )

        try:
            set_current_user("")
            assert get_current_user() == "system"
        finally:
            reset_current_user()


# ==================== W13-C3 追加：predict 审计用户归属（GUI 集成） ==================== #
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def predict_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.unit
def test_single_done_audit_records_logged_in_user(predict_qapp, monkeypatch):
    """W13-C3：登录后单张推理审计应记 user=登录名。

    RED：predict _single_done 此前调 log_detection_complete 不传 user，
    审计记录恒为默认 "system"，无法归属到登录用户。
    """
    from gui.pages.predict.page import PredictPage
    from core.session import reset_current_user, set_current_user

    class _FakeResult:
        boxes = None
        labels = []
        score = 0.0

    class _FakeHistory:
        def add_record(self, **kw):
            pass

    audit = []
    monkeypatch.setattr(
        "core.audit_logger.log_detection_complete",
        lambda **kw: audit.append(kw),
    )
    monkeypatch.setattr(
        "core.detection_history.get_history", lambda: _FakeHistory()
    )

    page = PredictPage()
    page._pending_single = ("missing.jpg", _FakeResult())
    set_current_user("engineer")
    try:
        page._single_done("missing.jpg", 0.5)
        assert audit, "单张推理完成应记审计"
        assert audit[0].get("user") == "engineer", (
            "推理审计应归属当前登录用户，而非默认 system"
        )
    finally:
        reset_current_user()
