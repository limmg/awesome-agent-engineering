"""AgentOps L01 测试：全局步数预算 + 运行时循环检测。

测试原则（对齐 conftest.py）：
    - 不调用真实 LLM（用 FakeLLM）
    - 开关默认关 → 现状行为不变（123 个现有测试不受影响）
    - 开了 enable_step_budget / enable_loop_detect → 触发诚实收尾
"""
from __future__ import annotations

import pytest

from research_assistant import config
from research_assistant.step_budget import (
    step_delta, detect_loop, should_truncate, honest_truncation_delta,
)


# ── step_delta：每个节点记账 ────────────────────────────────

def test_step_delta_returns_count_and_history():
    """step_delta 应返回 step_count=1 和一条 action_history 签名。"""
    d = step_delta("writer", "某个摘要内容")
    assert d["step_count"] == 1
    assert len(d["action_history"]) == 1
    assert d["action_history"][0].startswith("writer:")


def test_step_delta_signature_stable_for_same_param():
    """相同节点+相同参数 → 相同签名（循环检测的前提）。"""
    d1 = step_delta("reviewer", "rework")
    d2 = step_delta("reviewer", "rework")
    assert d1["action_history"][0] == d2["action_history"][0]


def test_step_delta_signature_differs_for_diff_param():
    """相同节点+不同参数 → 不同签名。"""
    d1 = step_delta("reviewer", "rework")
    d2 = step_delta("reviewer", "pass")
    assert d1["action_history"][0] != d2["action_history"][0]


# ── detect_loop：动作签名滑窗重复检测 ──────────────────────

def test_detect_loop_no_history():
    assert detect_loop([]) is False


def test_detect_loop_below_window():
    """签名数不足 window 不判循环。"""
    # 默认 window=3
    assert detect_loop(["reviewer:x", "reviewer:x"]) is False


def test_detect_loop_detected():
    """连续 window 个相同签名 → 判循环。"""
    hist = ["writer:a", "reviewer:b", "reviewer:b", "reviewer:b"]
    assert detect_loop(hist, window=3) is True


def test_detect_loop_not_detected_when_mixed():
    """末尾 window 个里有不同签名 → 不判循环。"""
    hist = ["reviewer:b", "reviewer:b", "reviewer:c"]
    assert detect_loop(hist, window=3) is False


# ── should_truncate：开关 + 条件 ────────────────────────────

def test_should_truncate_off_when_disabled():
    """开关都关 → 永不截断（现状行为）。"""
    config.settings.__dict__["enable_step_budget"] = False
    config.settings.__dict__["enable_loop_detect"] = False
    config.settings.__dict__["max_total_steps"] = 30
    truncate, reason = should_truncate({"step_count": 1000, "action_history": ["x"] * 100})
    assert truncate is False
    assert reason == ""


def test_should_truncate_on_step_budget_exceeded():
    """enable_step_budget 且步数超限 → 截断。"""
    config.settings.__dict__["enable_step_budget"] = True
    config.settings.__dict__["enable_loop_detect"] = False
    config.settings.__dict__["max_total_steps"] = 10
    truncate, reason = should_truncate({"step_count": 12, "action_history": []})
    assert truncate is True
    assert "步数预算" in reason


def test_should_truncate_not_triggered_within_budget():
    """enable_step_budget 但步数未超限 → 不截断。"""
    config.settings.__dict__["enable_step_budget"] = True
    config.settings.__dict__["enable_loop_detect"] = False
    config.settings.__dict__["max_total_steps"] = 30
    truncate, _ = should_truncate({"step_count": 5, "action_history": []})
    assert truncate is False


def test_should_truncate_on_loop_detected():
    """enable_loop_detect 且检测到循环 → 截断。"""
    config.settings.__dict__["enable_step_budget"] = False
    config.settings.__dict__["enable_loop_detect"] = True
    config.settings.__dict__["loop_detect_window"] = 3
    hist = ["reviewer:b", "reviewer:b", "reviewer:b"]
    truncate, reason = should_truncate({"action_history": hist})
    assert truncate is True
    assert "循环" in reason


def test_honest_truncation_delta_marks_truncated():
    """诚实收尾 delta 应标记 truncated=True。"""
    d = honest_truncation_delta("测试原因")
    assert d == {"truncated": True}


# ── 端到端：开关开时 reviewer 触发诚实收尾 ─────────────────

@pytest.mark.asyncio
async def test_reviewer_truncates_when_step_budget_exceeded(fake_llm):
    """开启步数预算 + 步数已超限 → reviewer 强制 pass 并标 truncated。"""
    config.settings.__dict__["enable_step_budget"] = True
    config.settings.__dict__["enable_loop_detect"] = False
    config.settings.__dict__["max_total_steps"] = 3

    from research_assistant.nodes import make_reviewer
    smart = fake_llm({"评估": "不合格\n结构不完整"})
    reviewer = make_reviewer(smart)

    state = {
        "report": "某报告", "rewrite_count": 0, "re_research_count": 0,
        "findings": [], "step_count": 10, "action_history": [],
    }
    result = reviewer(state)
    assert result["review_decision"] == "pass"
    assert result["truncated"] is True
    assert "诚实收尾" in result["feedback"]


@pytest.mark.asyncio
async def test_reviewer_normal_when_budget_off(fake_llm):
    """开关关时 reviewer 走正常审稿（不截断）。"""
    config.settings.__dict__["enable_step_budget"] = False
    config.settings.__dict__["enable_loop_detect"] = False

    from research_assistant.nodes import make_reviewer
    smart = fake_llm({"评估": "不合格\n结构不完整"})
    reviewer = make_reviewer(smart)

    state = {
        "report": "某报告", "rewrite_count": 0, "re_research_count": 0,
        "findings": [], "step_count": 1000, "action_history": [],
    }
    result = reviewer(state)
    # 步数很高但开关关 → 正常审稿（不合格 → rework）
    assert result["review_decision"] == "rework"
    assert "truncated" not in result or result.get("truncated") is False


def test_writer_annotates_truncation(fake_llm):
    """truncated=True 时 writer 应在报告里标注截断。"""
    config.settings.__dict__["enable_step_budget"] = False
    from research_assistant.nodes import make_writer
    smart = fake_llm({"报告": "正常报告内容"})
    writer = make_writer(smart)

    state = {
        "research_summary": "摘要", "feedback": "",
        "truncated": True,
    }
    result = writer(state)
    assert "截断" in result["report"]
    assert "部分结果" in result["report"]


def test_writer_no_annotation_when_not_truncated(fake_llm):
    """truncated=False 时 writer 不标注（现状行为）。"""
    config.settings.__dict__["enable_step_budget"] = False
    from research_assistant.nodes import make_writer
    smart = fake_llm({"报告": "正常报告内容"})
    writer = make_writer(smart)

    state = {"research_summary": "摘要", "feedback": "", "truncated": False}
    result = writer(state)
    assert "截断" not in result["report"]
