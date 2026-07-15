"""AgentOps L04 测试：副作用工具 + 幂等键。

测试原则（对齐 conftest.py）：
    - 不调用真实 LLM / 不联网
    - 发布注册表用 tmp_path 隔离（不污染生产 db）
    - 幂等键：同一 thread+内容 → no-op；内容变了 → 新发布
"""
from __future__ import annotations

import pytest

from research_assistant import config, publish


@pytest.fixture(autouse=True)
def _isolate_publish_db(tmp_path, monkeypatch):
    """每个测试用独立的发布注册表 + 关闭开关。"""
    db = tmp_path / "publish.db"
    monkeypatch.setattr(publish, "_DB_PATH", str(db))
    config.settings.__dict__["enable_publish"] = False
    config.settings.__dict__["publish_dry_run"] = False
    yield


# ── idempotency_key ─────────────────────────────────────────

def test_key_stable_for_same_thread_and_content():
    """同一 thread + 同一内容 → 同一 key（幂等前提）。"""
    k1 = publish.idempotency_key("thread-1", "报告内容")
    k2 = publish.idempotency_key("thread-1", "报告内容")
    assert k1 == k2


def test_key_differs_for_diff_content():
    """同 thread + 不同内容 → 不同 key（改进版要能发布）。"""
    k1 = publish.idempotency_key("thread-1", "第一版")
    k2 = publish.idempotency_key("thread-1", "第二版（改进）")
    assert k1 != k2


def test_key_differs_for_diff_thread():
    """不同 thread + 同内容 → 不同 key（会话隔离）。"""
    k1 = publish.idempotency_key("thread-1", "报告")
    k2 = publish.idempotency_key("thread-2", "报告")
    assert k1 != k2


# ── publish_report：首次发布 ────────────────────────────────

def test_publish_first_time():
    """首次发布 → published=True, idempotent_replay=False。"""
    r = publish.publish_report("t1", "报告内容")
    assert r["published"] is True
    assert r["idempotent_replay"] is False
    assert r["seq"] == 1
    assert r["output_path"] is not None


def test_publish_writes_output_file(tmp_path):
    """发布应写一个 outputs/ 文件。"""
    r = publish.publish_report("t1", "报告内容")
    from pathlib import Path
    p = Path(r["output_path"])
    assert p.exists()
    assert p.read_text(encoding="utf-8") == "报告内容"


# ── publish_report：幂等重放（核心）────────────────────────

def test_publish_idempotent_replay_same_content():
    """同 thread + 同内容第二次发布 → no-op（idempotent_replay=True）。"""
    r1 = publish.publish_report("t1", "报告内容")
    r2 = publish.publish_report("t1", "报告内容")
    assert r1["published"] is True
    assert r2["idempotent_replay"] is True  # ← 幂等：返回上次结果，不重复执行
    assert r2["key"] == r1["key"]


def test_publish_new_content_after_rewrite():
    """reviewer 打回重写后内容不同 → 新发布（不算重复）。"""
    r1 = publish.publish_report("t1", "第一版")
    r2 = publish.publish_report("t1", "第二版（改进）")
    assert r1["idempotent_replay"] is False
    assert r2["idempotent_replay"] is False  # 内容变了 → 新发布
    assert r2["seq"] == 2


def test_publish_same_content_across_replay_no_duplicate_in_history():
    """同一内容重复发布，发布历史里只记一次（去重）。"""
    publish.publish_report("t1", "内容A")
    publish.publish_report("t1", "内容A")  # 幂等 no-op
    publish.publish_report("t1", "内容A")  # 幂等 no-op
    history = publish.get_publish_history("t1")
    assert len(history) == 1  # 去重后只有一条


# ── dry-run ─────────────────────────────────────────────────

def test_publish_dry_run_does_not_execute():
    """dry-run → 只打印不真执行，published=False。"""
    config.settings.__dict__["publish_dry_run"] = True
    r = publish.publish_report("t1", "报告")
    assert r["published"] is False
    assert r["dry_run"] is True
    assert r["output_path"] is None
    # 注册表里不应有记录
    assert publish.get_publish_history("t1") == []


def test_publish_dry_run_explicit_param():
    """dry_run 参数优先于 config。"""
    r = publish.publish_report("t1", "报告", dry_run=True)
    assert r["published"] is False
    assert r["dry_run"] is True


# ── get_publish_history ─────────────────────────────────────

def test_publish_history_orders_by_time():
    publish.publish_report("t1", "v1")
    publish.publish_report("t1", "v2")
    publish.publish_report("t1", "v3")
    history = publish.get_publish_history("t1")
    assert len(history) == 3
    # 按时间升序
    times = [h["published_at"] for h in history]
    assert times == sorted(times)


def test_publish_history_isolated_by_thread():
    publish.publish_report("t1", "内容")
    publish.publish_report("t2", "内容")
    assert len(publish.get_publish_history("t1")) == 1
    assert len(publish.get_publish_history("t2")) == 1


# ── 图结构：enable_publish 开关 ─────────────────────────────

def test_graph_no_publish_node_when_disabled(fake_llm):
    """enable_publish=False 时图没有 publish 节点（现状等价）。"""
    config.settings.__dict__["enable_publish"] = False
    from research_assistant.graph import build_research_subgraph, build_system
    smart = fake_llm({"整理": "摘要", "报告": "报告", "评估": "合格"})
    fast = fake_llm({"拆": "1. a\n2. b", "回答": "发现", "提炼": "结果"})
    sub = build_research_subgraph(fast, smart)
    system = build_system(smart, fast, sub)
    nodes = set(system.get_graph().nodes.keys())
    assert "publish" not in nodes
    assert {"research_team", "writer", "reviewer"} <= nodes


def test_graph_has_publish_node_when_enabled(fake_llm):
    """enable_publish=True 时图多了 publish 节点。"""
    config.settings.__dict__["enable_publish"] = True
    from research_assistant.graph import build_research_subgraph, build_system
    smart = fake_llm({"整理": "摘要", "报告": "报告", "评估": "合格"})
    fast = fake_llm({"拆": "1. a\n2. b", "回答": "发现", "提炼": "结果"})
    sub = build_research_subgraph(fast, smart)
    system = build_system(smart, fast, sub)
    nodes = set(system.get_graph().nodes.keys())
    assert "publish" in nodes
    assert {"research_team", "writer", "reviewer", "publish"} <= nodes
