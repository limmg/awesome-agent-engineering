"""AgentOps L07 测试：轨迹级可观测（run summary + 阈值告警）。

测试原则（对齐 conftest.py）：
    - 不调用真实 LLM
    - 从 mock state 构建 summary，验证字段提取 + 阈值告警
"""
from __future__ import annotations

import pytest

from research_assistant import config
from research_assistant.run_summary import (
    RunSummary, build_summary, format_summary_line, emit_summary,
    _check_alerts, ALERT_THRESHOLDS,
)


@pytest.fixture(autouse=True)
def _reset_flags():
    config.settings.__dict__["enable_run_summary"] = False
    config.settings.__dict__["enable_cost_budget"] = False
    config.settings.__dict__["max_budget_tokens"] = 50000
    config.settings.__dict__["enable_hitl"] = False
    config.settings.__dict__["alert_steps_high"] = 25
    config.settings.__dict__["alert_budget_ratio_high"] = 0.9
    config.settings.__dict__["alert_degraded_high"] = 2
    yield


# ── build_summary：字段提取 ─────────────────────────────────

def test_build_summary_completed():
    """正常完成的 summary。"""
    state = {
        "step_count": 8, "token_usage": 1200, "cost_mode": "normal",
        "failed_subtopics": [], "truncated": False, "feedback": "",
        "publish_result": {"published": True, "idempotent_replay": False},
    }
    s = build_summary(state, run_id="r1", thread_id="t1", topic="主题")
    assert s.outcome == "completed"
    assert s.total_steps == 8
    assert s.total_tokens == 1200
    assert s.published is True
    assert s.alerts == []  # 无告警


def test_build_summary_truncated():
    """步数截断的 summary（truncated=True）。"""
    state = {
        "step_count": 30, "token_usage": 5000, "cost_mode": "over_budget",
        "failed_subtopics": [], "truncated": True, "feedback": "步数预算超限",
        "publish_result": {},
    }
    s = build_summary(state)
    assert s.outcome == "truncated"
    assert s.truncated if hasattr(s, 'truncated') else True


def test_build_summary_with_degraded():
    """检索降级的 summary。"""
    state = {
        "step_count": 5, "token_usage": 100, "cost_mode": "normal",
        "failed_subtopics": ["子题1（超时）", "子题2（错误）", "子题3（熔断）"],
        "truncated": False, "publish_result": {},
    }
    s = build_summary(state)
    assert s.degraded_subtopics == 3


def test_build_summary_publish_replayed():
    """幂等重放的 summary。"""
    state = {
        "step_count": 5, "token_usage": 100, "cost_mode": "normal",
        "failed_subtopics": [], "truncated": False,
        "publish_result": {"published": True, "idempotent_replay": True},
    }
    s = build_summary(state)
    assert s.published is True
    assert s.publish_replayed is True


def test_build_summary_approval_rejected():
    """审批否决的 summary。"""
    state = {
        "step_count": 5, "token_usage": 100, "cost_mode": "normal",
        "failed_subtopics": [], "truncated": False,
        "publish_result": {"published": False, "rejected": True},
    }
    s = build_summary(state)
    assert s.approval_rejected is True
    assert s.outcome == "truncated"  # 否决走诚实收尾


# ── 阈值告警 ────────────────────────────────────────────────

def test_alert_steps_high():
    """步数超阈值 → 告警。"""
    config.settings.__dict__["alert_steps_high"] = 25
    s = RunSummary(total_steps=30)
    alerts = _check_alerts(s)
    assert any("步数过高" in a for a in alerts)


def test_alert_no_steps_when_below_threshold():
    s = RunSummary(total_steps=10)
    alerts = _check_alerts(s)
    assert not any("步数过高" in a for a in alerts)


def test_alert_budget_ratio_high():
    """预算比例超阈值 → 告警。"""
    s = RunSummary(budget_ratio=0.95)
    alerts = _check_alerts(s)
    assert any("预算将耗尽" in a for a in alerts)


def test_alert_degraded_high():
    """降级子题多 → 告警。"""
    s = RunSummary(degraded_subtopics=3)
    alerts = _check_alerts(s)
    assert any("降级子题多" in a for a in alerts)


def test_alert_breaker_tripped():
    """熔断器打开过 → 告警。"""
    s = RunSummary(breaker_tripped=True)
    alerts = _check_alerts(s)
    assert any("熔断器" in a for a in alerts)


def test_no_alerts_on_healthy_run():
    """健康跑无告警。"""
    s = RunSummary(total_steps=8, budget_ratio=0.1, degraded_subtopics=0,
                   loop_brakes=0, breaker_tripped=False)
    assert _check_alerts(s) == []


# ── format_summary_line ─────────────────────────────────────

def test_format_summary_line_has_icon():
    s = RunSummary(outcome="completed", total_steps=8, total_tokens=100)
    line = format_summary_line(s)
    assert "✅" in line
    assert "steps=8" in line
    assert "tokens=100" in line


def test_format_summary_line_includes_alerts():
    s = RunSummary(outcome="truncated", total_steps=30, alerts=["⚠️ 步数过高"])
    line = format_summary_line(s)
    assert "步数过高" in line


# ── emit_summary：不抛异常 ──────────────────────────────────

def test_emit_summary_runs(capsys):
    """emit_summary 应正常输出（不抛异常）。"""
    s = RunSummary(outcome="completed", total_steps=8, total_tokens=100)
    emit_summary(s)  # 不抛即可
    s2 = RunSummary(outcome="truncated", total_steps=30, alerts=["⚠️ 步数过高"])
    emit_summary(s2)  # 有告警也不抛


# ── 六类故障各跑一次 → 六行 summary 对比 ───────────────────

def test_six_faults_summary_comparison():
    """模拟六类故障各跑一次，对比六行 summary。"""
    configs = [
        ("pure",   {"step_count": 7,  "token_usage": 142,  "failed_subtopics": [], "truncated": False, "publish_result": {}, "cost_mode": "normal"}),
        ("slow",   {"step_count": 7,  "token_usage": 124,  "failed_subtopics": ["子题1（超时）"], "truncated": False, "publish_result": {}, "cost_mode": "normal"}),
        ("flaky",  {"step_count": 7,  "token_usage": 162,  "failed_subtopics": ["子题1（错误）"], "truncated": False, "publish_result": {}, "cost_mode": "normal"}),
        ("loop",   {"step_count": 11, "token_usage": 220,  "failed_subtopics": [], "truncated": False, "feedback": "循环检测", "publish_result": {}, "cost_mode": "normal"}),
        ("crash",  {"step_count": 8,  "token_usage": 115,  "failed_subtopics": [], "truncated": False, "publish_result": {}, "cost_mode": "normal"}),
        ("bomb",   {"step_count": 7,  "token_usage": 70714,"failed_subtopics": [], "truncated": False, "publish_result": {}, "cost_mode": "over_budget"}),
    ]
    summaries = []
    for name, state in configs:
        s = build_summary(state, run_id=name)
        summaries.append(s)
    # 六行都有，每行有 outcome
    assert len(summaries) == 6
    assert all(s.outcome in ("completed", "truncated") for s in summaries)
    # bomb 场景 token 最高
    bomb = next(s for s in summaries if s.run_id == "bomb")
    assert bomb.total_tokens == max(s.total_tokens for s in summaries)
