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
