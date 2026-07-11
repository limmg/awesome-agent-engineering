"""节点逻辑测试：用 mock LLM 验证各节点的输入输出契约。

不调用真实 LLM，不联网。验证节点的"转换逻辑"正确性。
"""
from __future__ import annotations

import asyncio

import pytest

from research_assistant import nodes
from research_assistant.state import ResearchState, SystemState


# ── split 节点 ──────────────────────────────────────────────
def test_split_extracts_subtopics(fake_llm, monkeypatch):
    """split 应从 LLM 回复中解析出子问题列表。"""
    import research_assistant.config as config
    config.settings.__dict__["num_subtopics"] = 3  # 本测试明确要 3 个

    llm = fake_llm({"拆": "1. 第一个问题\n2. 第二个问题\n3. 第三个问题"})
    split = nodes.make_split(llm)

    result = split({"topic": "测试主题", "subtopics": [], "findings": [], "research_summary": ""})

    assert "subtopics" in result
    assert len(result["subtopics"]) == 3
    assert "第一个问题" in result["subtopics"][0]


def test_split_strips_numbering(fake_llm):
    """split 应去除编号前缀（1. 2、) 等）。"""
    llm = fake_llm({"拆": "1）带括号编号的问题\n2. 带点编号的问题"})
    split = nodes.make_split(llm)

    result = split({"topic": "x", "subtopics": [], "findings": [], "research_summary": ""})
    for s in result["subtopics"]:
        assert not s[0].isdigit(), f"子问题不应带数字前缀: {s}"


def test_split_respects_num_subtopics(fake_llm, monkeypatch):
    """split 应只返回 num_subtopics 个子问题（即使 LLM 给更多）。"""
    import research_assistant.config as config
    config.settings.__dict__["num_subtopics"] = 2  # 限制为 2

    llm = fake_llm({"拆": "1. 一\n2. 二\n3. 三\n4. 四"})
    split = nodes.make_split(llm)

    result = split({"topic": "x", "subtopics": [], "findings": [], "research_summary": ""})
    assert len(result["subtopics"]) <= 2


# ── researcher 节点（async）──────────────────────────────────
@pytest.mark.asyncio
async def test_researcher_with_search_results(fake_llm, monkeypatch):
    """researcher 有搜索素材时，应标注真实来源。"""
    async def fake_web_search(query, max_results=None):
        return "[1] 真实标题\n    真实内容\n    来源: http://real.com"
    monkeypatch.setattr(nodes, "web_search", fake_web_search)

    llm = fake_llm({"针对": "这是基于资料的提炼"})
    researcher = nodes.make_researcher(llm)

    result = await researcher({"subtopic": "测试子题"})
    assert "findings" in result
    assert len(result["findings"]) == 1
    assert "真实联网搜索" in result["findings"][0]
    assert "测试子题" in result["findings"][0]


@pytest.mark.asyncio
async def test_researcher_fallback_on_search_failure(fake_llm, monkeypatch):
    """researcher 搜索失败时，应降级到模型知识并诚实标注。"""
    async def failing_search(query, max_results=None):
        return "搜索 'x' 没有返回结果。"
    monkeypatch.setattr(nodes, "web_search", failing_search)

    llm = fake_llm({"回答": "模型自身知识的回答"})
    researcher = nodes.make_researcher(llm)

    result = await researcher({"subtopic": "某子题"})
    assert "模型知识" in result["findings"][0], "搜索失败应标注降级来源"
    assert "联网搜索暂不可用" in result["findings"][0]


@pytest.mark.asyncio
async def test_researcher_appends_to_findings(fake_llm, monkeypatch):
    """researcher 返回的 findings 是列表（reducer 自动拼接的前提）。"""
    async def fake_search(query, max_results=None):
        return "有效内容"
    monkeypatch.setattr(nodes, "web_search", fake_search)

    researcher = nodes.make_researcher(fake_llm({"提炼": "发现"}))
    result = await researcher({"subtopic": "x"})
    assert isinstance(result["findings"], list)


# ── summarize 节点 ──────────────────────────────────────────
def test_summarize_produces_summary(fake_llm):
    """summarize 应把 findings 合并成 research_summary。"""
    llm = fake_llm({"整理": "这是综合摘要"})
    summarize = nodes.make_summarize(llm)

    result = summarize({
        "topic": "x", "subtopics": [],
        "findings": ["发现1", "发现2", "发现3"], "research_summary": "",
    })
    assert result["research_summary"] == "这是综合摘要"


# ── writer 节点 ─────────────────────────────────────────────
def test_writer_generates_report(fake_llm):
    """writer 应生成 report 并写入 messages。"""
    llm = fake_llm({"研究报告": "生成的报告内容"})
    writer = nodes.make_writer(llm)

    result = writer({
        "messages": [], "findings": [], "research_summary": "摘要",
        "report": "", "review_decision": "", "rewrite_count": 0, "feedback": "",
    })
    assert result["report"] == "生成的报告内容"
    assert len(result["messages"]) == 1  # AIMessage


def test_writer_uses_feedback(fake_llm):
    """writer 有 feedback 时，prompt 应包含反馈（通过调用计数验证）。"""
    captured = {}
    class CaptureLLM:
        def invoke(self, prompt, **kw):
            captured["prompt"] = prompt
            from research_assistant.nodes import AIMessage  # 已 import
            class M: content = "改后的报告"
            return M()

    writer = nodes.make_writer(CaptureLLM())
    writer({
        "messages": [], "findings": [], "research_summary": "摘要",
        "report": "", "review_decision": "", "rewrite_count": 1,
        "feedback": "报告太短，请扩展",
    })
    assert "审稿反馈" in captured["prompt"]
    assert "报告太短" in captured["prompt"]


# ── reviewer 节点 ───────────────────────────────────────────
def test_reviewer_pass_on_qualified(fake_llm):
    """reviewer 收到"合格"回复时应判定 pass。"""
    llm = fake_llm({"评估": "合格"})
    reviewer = nodes.make_reviewer(llm)

    result = reviewer({
        "messages": [], "findings": [], "research_summary": "",
        "report": "一份报告", "review_decision": "", "rewrite_count": 0, "feedback": "",
    })
    assert result["review_decision"] == "pass"
    assert result["rewrite_count"] == 1


def test_reviewer_rework_on_unqualified(fake_llm):
    """reviewer 收到"不合格"时应判定 rework 并带 feedback。"""
    llm = fake_llm({"评估": "不合格\n报告结构不完整"})
    reviewer = nodes.make_reviewer(llm)

    result = reviewer({
        "messages": [], "findings": [], "research_summary": "",
        "report": "差报告", "review_decision": "", "rewrite_count": 0, "feedback": "",
    })
    assert result["review_decision"] == "rework"
    assert "结构不完整" in result["feedback"]


def test_reviewer_force_pass_at_max_rewrites(fake_llm):
    """rewrite_count 达上限时，reviewer 应强制 pass（防死循环）。"""
    import research_assistant.config as config
    config.settings.__dict__["max_rewrites"] = 2

    llm = fake_llm({"评估": "不合格"})  # 即使说不合格
    reviewer = nodes.make_reviewer(llm)

    result = reviewer({
        "messages": [], "findings": [], "research_summary": "",
        "report": "报告", "review_decision": "", "rewrite_count": 2, "feedback": "",
    })
    assert result["review_decision"] == "pass"  # 强制通过
    assert "强制通过" in result["feedback"]


def test_review_route_pass_to_end():
    """条件边：decision=pass → END（langgraph 的 END sentinel）。"""
    from langgraph.graph import END
    result = nodes.review_route({
        "review_decision": "pass", "rewrite_count": 1,
        "messages": [], "findings": [], "research_summary": "", "report": "", "feedback": "",
    })
    assert result == END


def test_review_route_rework_to_writer():
    """条件边：decision=rework 且未达上限 → writer。"""
    import research_assistant.config as config
    config.settings.__dict__["max_rewrites"] = 5

    result = nodes.review_route({
        "review_decision": "rework", "rewrite_count": 1,
        "messages": [], "findings": [], "research_summary": "", "report": "", "feedback": "",
        "conflicts": [], "re_research_count": 0, "re_research_queries": [],
    })
    assert result == "writer"


# ── Frontier L05：双通道 reviewer + 冲突检测 ─────────────────
def test_review_route_re_research_to_research_team():
    """条件边：decision=re_research 且未超限 → research_team。"""
    import research_assistant.config as config
    config.settings.__dict__["max_re_research"] = 3

    result = nodes.review_route({
        "review_decision": "re_research", "rewrite_count": 0,
        "messages": [], "findings": [], "research_summary": "", "report": "", "feedback": "",
        "conflicts": ["冲突1"], "re_research_count": 1, "re_research_queries": ["验证X"],
    })
    assert result == "research_team"


def test_review_route_re_research_at_limit_to_end():
    """条件边：re_research 超限 → END（防死循环）。"""
    from langgraph.graph import END
    import research_assistant.config as config
    config.settings.__dict__["max_re_research"] = 2

    result = nodes.review_route({
        "review_decision": "re_research", "rewrite_count": 0,
        "messages": [], "findings": [], "research_summary": "", "report": "", "feedback": "",
        "conflicts": ["冲突1"], "re_research_count": 3, "re_research_queries": ["验证X"],
    })
    assert result == END


def test_check_conflicts_detects_with_llm():
    """冲突检测：LLM 判"冲突"时应返回冲突 + 补研问题。"""
    class ConflictLLM:
        def invoke(self, prompt, **kw):
            class R:
                content = ""
            if "只回复一个词" in prompt:
                R.content = "冲突"
            else:
                R.content = "验证 MCP 到底基于什么协议"
            return R()

    class FakeMemStore:
        def recall(self, query, k=3):
            from research_assistant.memory import SemanticMemory
            import time
            return {"episodic": [], "semantic": [SemanticMemory("id", "MCP", "MCP基于gRPC", "依据", time.time(), 0.8)]}

    findings = ["MCP 协议实际上基于 JSON-RPC 而非 gRPC"]
    result = nodes.check_conflicts(findings, FakeMemStore(), ConflictLLM())
    assert len(result["conflicts"]) > 0
    assert len(result["queries"]) > 0


def test_check_conflicts_no_conflict_when_consistent():
    """冲突检测：LLM 判"一致"时不应返回冲突。"""
    class ConsistentLLM:
        def invoke(self, prompt, **kw):
            class R:
                content = "一致"
            return R()

    class FakeMemStore:
        def recall(self, query, k=3):
            from research_assistant.memory import SemanticMemory
            import time
            return {"episodic": [], "semantic": [SemanticMemory("id", "MCP", "MCP基于JSON-RPC", "依据", time.time(), 0.8)]}

    findings = ["MCP 协议基于 JSON-RPC 2.0"]
    result = nodes.check_conflicts(findings, FakeMemStore(), ConsistentLLM())
    assert len(result["conflicts"]) == 0


def test_check_conflicts_rule_fallback():
    """冲突检测：无 LLM 时降级为关键词检测。"""
    class FakeMemStore:
        def recall(self, query, k=3):
            from research_assistant.memory import SemanticMemory
            import time
            return {"episodic": [], "semantic": [SemanticMemory("id", "MCP", "旧结论", "依据", time.time(), 0.8)]}

    # 含"修正"信号词 → 检测到冲突
    findings = ["修正：MCP 实际上基于 JSON-RPC"]
    result = nodes.check_conflicts(findings, FakeMemStore(), llm=None)
    assert len(result["conflicts"]) > 0


def test_check_conflicts_no_old_memory():
    """冲突检测：无旧记忆时不检测冲突。"""
    class FakeMemStore:
        def recall(self, query, k=3):
            return {"episodic": [], "semantic": []}

    findings = ["一些新发现"]
    result = nodes.check_conflicts(findings, FakeMemStore(), llm=None)
    assert len(result["conflicts"]) == 0
