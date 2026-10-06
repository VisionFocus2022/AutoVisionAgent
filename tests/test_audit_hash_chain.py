"""审计哈希链测试（M6 防篡改，2026-10-06）。

契约：
- 正常写入 → 链完整（verify_chain 空）
- 离线编辑任意历史行（改内容/删行）→ 断链被检出
- legacy 无哈希行与链区共存 → legacy 段跳过不误报
- 跨 flush/跨进程（新实例同目录）→ 链延续
"""
from __future__ import annotations

import json

import pytest

from core.audit_logger import AuditLogger


@pytest.fixture
def audit(tmp_path):
    """单例重置 + 独立目录的审计实例。"""
    AuditLogger._instance = None
    inst = AuditLogger(log_dir=tmp_path / "audit")
    yield inst
    AuditLogger._instance = None


def _today_file(audit) -> object:
    from datetime import datetime

    return audit._log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"


@pytest.mark.unit
def test_chain_intact_on_normal_writes(audit):
    """正常写三条 → 全部落盘带哈希且链校验通过。"""
    audit.log("login", user="alice")
    audit.log("inference", user="alice", task="det")
    audit.log("train_complete", user="bob", epochs=10)
    audit.flush()

    f = _today_file(audit)
    assert f.exists()
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    entries = [json.loads(x) for x in lines]
    assert all("self_hash" in e and "prev_hash" in e and "seq" in e for e in entries)
    # 链衔接：第 2/3 条 prev_hash == 前一条 self_hash
    assert entries[1]["prev_hash"] == entries[0]["self_hash"]
    assert entries[2]["prev_hash"] == entries[1]["self_hash"]
    assert audit.verify_chain() == []


@pytest.mark.unit
def test_tampered_line_detected(audit):
    """离线编辑历史行内容 → self_hash 重算不符，断链检出。"""
    audit.log("login", user="alice")
    audit.log("export", user="alice", path="x.onnx")
    audit.flush()

    f = _today_file(audit)
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    # 篡改第 1 条：改 user
    entry = json.loads(lines[0])
    entry["user"] = "mallory"
    lines[0] = json.dumps(entry, ensure_ascii=False)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")

    broken = audit.verify_chain()
    assert 1 in broken, f"篡改行未检出: {broken}"


@pytest.mark.unit
def test_deleted_line_breaks_chain(audit):
    """删除中间行 → 后续 prev_hash 失联，断链检出。"""
    audit.log("a1", user="u")
    audit.log("a2", user="u")
    audit.log("a3", user="u")
    audit.flush()

    f = _today_file(audit)
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    del lines[1]  # 删第 2 行
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert audit.verify_chain() != [], "删行未检出"


@pytest.mark.unit
def test_legacy_lines_coexist_without_false_positive(audit):
    """legacy 无哈希行（旧版产物）与链区共存 → legacy 段不误报。"""
    f = _today_file(audit)
    audit._log_dir.mkdir(parents=True, exist_ok=True)
    legacy = json.dumps({"timestamp": "t", "action": "old", "user": "u"})
    f.write_text(legacy + "\n", encoding="utf-8")

    audit.log("new_event", user="u")  # 链自本条起
    audit.flush()

    assert audit.verify_chain() == [], "legacy 行不得误报断链"


@pytest.mark.unit
def test_chain_continues_across_instances(audit, tmp_path):
    """跨进程：新实例同目录续写 → 链从尾行延续而非重起。"""
    audit.log("first", user="u")
    audit.flush()

    # 模拟另一进程：新实例同目录
    AuditLogger._instance = None
    second = AuditLogger(log_dir=tmp_path / "audit")
    second.log("second", user="u")
    second.flush()

    f = _today_file(second)
    entries = [json.loads(x) for x in f.read_text(encoding="utf-8").strip().splitlines()]
    assert len(entries) == 2
    assert entries[1]["prev_hash"] == entries[0]["self_hash"], "跨实例链须延续"
    assert entries[1]["seq"] == entries[0]["seq"] + 1
    assert second.verify_chain() == []


@pytest.mark.unit
def test_seq_monotonic_and_hash_unique(audit):
    """seq 单调递增且各条 self_hash 互不相同。"""
    for i in range(5):
        audit.log("e", user="u", i=i)
    audit.flush()

    f = _today_file(audit)
    entries = [json.loads(x) for x in f.read_text(encoding="utf-8").strip().splitlines()]
    seqs = [e["seq"] for e in entries]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    hashes = [e["self_hash"] for e in entries]
    assert len(set(hashes)) == len(hashes)
