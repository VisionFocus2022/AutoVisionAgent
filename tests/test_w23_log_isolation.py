"""W23（v4 P2-1c）：测试态/生产态日志隔离——AVA_LOG_DIR 环境变量。

实证背景：tests/test_gui.py:210 main() 调用使 root 挂上仓库 logs/autovision.log
的 RotatingFileHandler 且零清理 → 会话全量测试日志混入生产可观测性文件
（autovision.log 51,647 行中 1,990 行 pytest-of）；serving/audit/history 三写入
方同病（serving.log 63 行、history_20260819.jsonl 含 "/test.jpg" 28 行）。

约定：AVA_LOG_DIR 显式指定时优先于 config 的 CWD 相对 ./logs 与 core 单例的
仓库绝对路径默认（gui.main.setup_logging / serving.server._resolve_log_dir /
core.audit_logger / core.detection_history 四写入方统一）；生产与打包 exe
不设该 env，行为不变。测试进程经根 conftest setdefault 指向会话临时目录。
"""
import logging
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_setup_logging_honors_ava_log_dir(tmp_path, monkeypatch):
    """AVA_LOG_DIR 显式指定 → 文件 handler 落该目录，而非 CWD 相对 ./logs。"""
    import gui.main as main_mod

    target = tmp_path / "ava-logs"
    monkeypatch.chdir(tmp_path)  # 旧实现写 tmp/logs（CWD 相对），RED 期不污染仓库
    monkeypatch.setenv("AVA_LOG_DIR", str(target))
    before = list(logging.getLogger().handlers)
    try:
        main_mod.setup_logging()
        added = [h for h in logging.getLogger().handlers if h not in before]
        assert any(
            Path(h.baseFilename).parent == target for h in added
        ), f"setup_logging 应落 AVA_LOG_DIR={target}，实际: " \
           f"{[h.baseFilename for h in added]}"
    finally:
        for h in list(logging.getLogger().handlers):
            if h not in before:
                h.close()
                logging.getLogger().removeHandler(h)


@pytest.mark.unit
def test_resolve_log_dir_honors_ava_log_dir(monkeypatch, tmp_path):
    target = tmp_path / "srv-logs"
    monkeypatch.setenv("AVA_LOG_DIR", str(target))
    from serving.server import _resolve_log_dir
    assert _resolve_log_dir() == str(target)


@pytest.mark.unit
def test_audit_and_history_default_dirs_env_aware(monkeypatch, tmp_path):
    """单例默认目录 env 感知（_instance 经 monkeypatch 还原，无跨用例残留）。"""
    from core import audit_logger, detection_history

    monkeypatch.setenv("AVA_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(audit_logger.AuditLogger, "_instance", None)
    monkeypatch.setattr(detection_history.DetectionHistory, "_instance", None)
    assert audit_logger.get_audit_logger()._log_dir == tmp_path / "audit"
    assert detection_history.get_history()._history_dir == tmp_path / "history"


@pytest.mark.unit
def test_audit_and_history_default_dirs_without_env(monkeypatch):
    """env 缺席时的生产默认：仓库 logs/audit、logs/history（与 W23 前
    逐字节一致——生产行为不变的回归锚，兼覆盖两 resolver 默认分支）。"""
    from core import audit_logger, detection_history
    from core.constants import CONFIG_DIR

    monkeypatch.delenv("AVA_LOG_DIR", raising=False)
    monkeypatch.setattr(audit_logger.AuditLogger, "_instance", None)
    monkeypatch.setattr(detection_history.DetectionHistory, "_instance", None)
    assert audit_logger.get_audit_logger()._log_dir == CONFIG_DIR.parent / "logs" / "audit"
    assert detection_history.get_history()._history_dir == CONFIG_DIR.parent / "logs" / "history"


@pytest.mark.unit
def test_root_conftest_wires_ava_log_dir():
    """源码守卫：根 conftest.py 含 AVA_LOG_DIR setdefault 接线（防回退，
    镜像 tests/test_uia_helpers_guard.py 手法）。"""
    src = (REPO_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "AVA_LOG_DIR" in src and "setdefault" in src


@pytest.mark.unit
def test_production_logs_free_of_test_pollution():
    """W24：logs/ 存量清档后的防复发锚——生产可观测性文件零测试签名。

    清档记录（2026-08-21 用户批准"存量污染可直接删除"）：autovision.log
    删 1,990 行 pytest-of；audit_20260630.jsonl 整文件删（7 行全为单测
    alice/bob/u1 记录）；audit_20260817/18 删 fake.png 各 25/22 行；
    history 各日删 "/test*.jpg" 与 fake.png 共 13+44+136+42+8 行。
    守卫签名只取铁证（W24 对抗验证员补强第四签名）：'pytest-of'（pytest
    临时根）+ 'fake.png'（fixture 名，仅查 jsonl 记录文件）+ 'tests\\test_'
    / 'tests/test_'（traceback 帧——生产用户异常栈不可能穿仓内测试目录，
    仅查 .log 文件，W24 首轮清档漏此签名残留 641 条测试异常记录 6,332 行
    被验证员 diff 备份擒获）；image_path 的 /test 前缀不入守卫——真实
    用户文件名可能撞 test.jpg（误报风险）。logs/ 缺席时 skip（非运行机/
    新克隆）。
    """
    logs_dir = REPO_ROOT / "logs"
    if not logs_dir.exists():
        pytest.skip("本机无 logs/（非运行机）")
    offenders = []
    files = sorted(logs_dir.rglob("*"))
    for f in files:
        if not f.is_file() or f.suffix not in (".log", ".jsonl"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(REPO_ROOT)
        if "pytest-of" in text:
            offenders.append(f"{rel}: pytest-of")
        if f.suffix == ".jsonl" and "fake.png" in text:
            offenders.append(f"{rel}: fake.png")
        if f.suffix == ".log" and ("tests\\test_" in text or "tests/test_" in text):
            offenders.append(f"{rel}: tests-frame")
    assert not offenders, f"生产日志混入测试签名: {offenders}"
