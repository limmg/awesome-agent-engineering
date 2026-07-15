"""AgentOps L05 测试：人在环审批（HITL）。

测试原则（对齐 conftest.py）：
    - 不调用真实 LLM（用 FakeLLM）
    - 用 InMemorySaver 作 checkpointer 测 interrupt/resume（不打真实 API）
    - 开关默认关 → 现状行为不变
"""
from __future__ import annotations

import pytest

from research_assistant import config, publish


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个测试用独立的发布注册表 + 还原开关。"""
    monkeypatch.setattr(publish, "_DB_PATH", str(tmp_path / "pub.db"))
    config.settings.__dict__["enable_publish"] = True
    config.settings.__dict__["enable_hitl"] = False
    config.settings.__dict__["hitl_policy"] = "first_only"
    config.settings.__dict__["publish_dry_run"] = False
    yield


# ── _needs_approval：策略判断 ───────────────────────────────

def test_needs_approval_auto_policy():
    """auto 策略 → 永不审批。"""
    config.settings.__dict__["hitl_policy"] = "auto"
    assert publish._needs_approval("t1", "内容") is False


def test_needs_approval_always_policy():
    """always 策略 → 每次都审。"""
    config.settings.__dict__["hitl_policy"] = "always"
    assert publish._needs_approval("t1", "内容") is True


def test_needs_approval_first_only_first_time():
    """first_only → 首次发布必审。"""
    config.settings.__dict__["hitl_policy"] = "first_only"
    assert publish._needs_approval("t1", "内容") is True


def test_needs_approval_first_only_after_published():
    """first_only → 已发布过（幂等重放）免审。"""
    config.settings.__dict__["hitl_policy"] = "first_only"
    publish.publish_report("t1", "内容")  # 先发布一次
    # 再查同内容 → 幂等重放 → 免审
    assert publish._needs_approval("t1", "内容") is False


# ── 端到端：interrupt/resume 审批流 ─────────────────────────

@pytest.mark.asyncio
async def test_publish_interrupts_for_approval(fake_llm):
    """enable_hitl + first_only → publish 节点 interrupt 暂停等审批。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from research_assistant.graph import build_research_subgraph, build_system

    config.settings.__dict__["enable_publish"] = True
    config.settings.__dict__["enable_hitl"] = True
    config.settings.__dict__["hitl_policy"] = "first_only"

    smart = fake_llm({"整理": "摘要", "报告": "报告内容", "评估": "合格"})
    fast = fake_llm({"拆": "1. a\n2. b", "回答": "发现", "提炼": "结果"})
    sub = build_research_subgraph(fast, smart)
    system = build_system(smart, fast, sub, checkpointer=InMemorySaver())

    cfg = {"configurable": {"thread_id": "hitl-test"}}
    init = {
        "messages": [{"role": "user", "content": "主题"}],
        "findings": [], "research_summary": "摘要", "report": "",
        "review_decision": "", "rewrite_count": 0, "feedback": "",
        "conflicts": [], "re_research_count": 0, "re_research_queries": [],
        "step_count": 0, "truncated": False, "action_history": [],
        "token_usage": 0, "cost_mode": "normal", "failed_subtopics": [],
        "publish_result": {},
    }
    # 第一次调用：会跑到 publish interrupt 暂停
    result = await system.ainvoke(init, config=cfg)
    # 应该看到 __interrupt__（暂停在 publish）
    assert "__interrupt__" in result or "publish" in str(result.get("__interrupt__", ""))

    # state.next 应包含 publish
    state = await system.aget_state(cfg)
    assert state.next and "publish" in state.next


@pytest.mark.asyncio
async def test_publish_approved_then_publishes(fake_llm):
    """审批通过 → resume → publish 执行。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from research_assistant.graph import build_research_subgraph, build_system

    config.settings.__dict__["enable_publish"] = True
    config.settings.__dict__["enable_hitl"] = True
    config.settings.__dict__["hitl_policy"] = "first_only"

    smart = fake_llm({"整理": "摘要", "报告": "报告内容", "评估": "合格"})
    fast = fake_llm({"拆": "1. a\n2. b", "回答": "发现", "提炼": "结果"})
    sub = build_research_subgraph(fast, smart)
    system = build_system(smart, fast, sub, checkpointer=InMemorySaver())

    cfg = {"configurable": {"thread_id": "approve-test"}}
    init = {
        "messages": [{"role": "user", "content": "主题"}],
        "findings": [], "research_summary": "摘要", "report": "",
        "review_decision": "", "rewrite_count": 0, "feedback": "",
        "conflicts": [], "re_research_count": 0, "re_research_queries": [],
        "step_count": 0, "truncated": False, "action_history": [],
        "token_usage": 0, "cost_mode": "normal", "failed_subtopics": [],
        "publish_result": {},
    }
    # 第一次：跑到 publish 暂停
    await system.ainvoke(init, config=cfg)
    # 批准：Command(resume={"approved": True})
    result = await system.ainvoke(Command(resume={"approved": True, "comment": "同意"}), config=cfg)
    # publish_result 应显示发布成功
    pr = result.get("publish_result", {})
    assert pr.get("published") is True or pr.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_publish_rejected_then_truncate(fake_llm):
    """审批否决 → resume → 走诚实收尾（不发布，标 truncated）。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from research_assistant.graph import build_research_subgraph, build_system

    config.settings.__dict__["enable_publish"] = True
    config.settings.__dict__["enable_hitl"] = True
    config.settings.__dict__["hitl_policy"] = "first_only"

    smart = fake_llm({"整理": "摘要", "报告": "报告内容", "评估": "合格"})
    fast = fake_llm({"拆": "1. a\n2. b", "回答": "发现", "提炼": "结果"})
    sub = build_research_subgraph(fast, smart)
    system = build_system(smart, fast, sub, checkpointer=InMemorySaver())

    cfg = {"configurable": {"thread_id": "reject-test"}}
    init = {
        "messages": [{"role": "user", "content": "主题"}],
        "findings": [], "research_summary": "摘要", "report": "",
        "review_decision": "", "rewrite_count": 0, "feedback": "",
        "conflicts": [], "re_research_count": 0, "re_research_queries": [],
        "step_count": 0, "truncated": False, "action_history": [],
        "token_usage": 0, "cost_mode": "normal", "failed_subtopics": [],
        "publish_result": {},
    }
    await system.ainvoke(init, config=cfg)
    # 否决：Command(resume={"approved": False})
    result = await system.ainvoke(Command(resume={"approved": False, "comment": "不要"}), config=cfg)
    pr = result.get("publish_result", {})
    assert pr.get("published") is False
    assert pr.get("rejected") is True
    # 否决走诚实收尾
    assert result.get("truncated") is True


@pytest.mark.asyncio
async def test_hitl_off_no_interrupt(fake_llm):
    """enable_hitl=False → publish 不 interrupt（直接发布）。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from research_assistant.graph import build_research_subgraph, build_system

    config.settings.__dict__["enable_publish"] = True
    config.settings.__dict__["enable_hitl"] = False

    smart = fake_llm({"整理": "摘要", "报告": "报告内容", "评估": "合格"})
    fast = fake_llm({"拆": "1. a\n2. b", "回答": "发现", "提炼": "结果"})
    sub = build_research_subgraph(fast, smart)
    system = build_system(smart, fast, sub, checkpointer=InMemorySaver())

    cfg = {"configurable": {"thread_id": "no-hitl-test"}}
    init = {
        "messages": [{"role": "user", "content": "主题"}],
        "findings": [], "research_summary": "摘要", "report": "",
        "review_decision": "", "rewrite_count": 0, "feedback": "",
        "conflicts": [], "re_research_count": 0, "re_research_queries": [],
        "step_count": 0, "truncated": False, "action_history": [],
        "token_usage": 0, "cost_mode": "normal", "failed_subtopics": [],
        "publish_result": {},
    }
    result = await system.ainvoke(init, config=cfg)
    # 不应 interrupt（直接发布完成）
    assert "__interrupt__" not in result
    pr = result.get("publish_result", {})
    assert pr.get("published") is True or pr.get("idempotent_replay") is True
