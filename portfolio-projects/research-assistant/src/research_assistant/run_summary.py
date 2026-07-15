"""轨迹级可观测：一次运行一行体检报告（AgentOps L07）。

与 ops-L01/L02 请求级观测的区别：
    - ops 看的是「单次请求」（span 级日志/tracing）——回答「这一步发生了什么」
    - 本课看的是「整条轨迹」的运行级聚合——回答「这次跑得健康吗」

run summary 字段设计对齐 frontier-L08 轨迹评估，以便复用分析脚本：
    - 评估算质量指标（事后、离线、批量）
    - 观测算健康指标（实时、在线、单次）
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from .config import settings
from .logging_config import get_logger

log = get_logger("run_summary")

# 结局分类
OUTCOMES = {
    "completed": "正常完成",
    "truncated": "诚实截断（步数/成本/审批否决）",
    "failed": "失败（崩溃/错误）",
    "awaiting_approval": "等审批中",
}


@dataclass
class RunSummary:
    """一次运行的体检报告（一行结构化汇总）。"""
    run_id: str = ""
    thread_id: str = ""
    topic: str = ""
    # ── 步数（L01）──
    total_steps: int = 0
    loop_brakes: int = 0           # 循环检测触发次数
    # ── 成本（L02）──
    total_tokens: int = 0
    budget_ratio: float = 0.0      # token / max_budget
    cost_mode: str = "normal"      # normal/frugal/over_budget
    # ── 降级（L03）──
    degraded_subtopics: int = 0    # 检索失败子题数
    breaker_tripped: bool = False  # 熔断器是否打开过
    # ── 副作用（L04/L05）──
    published: bool = False
    publish_replayed: bool = False # 幂等重放
    approval_waited: bool = False  # 是否等过审批
    approval_rejected: bool = False
    # ── 恢复（L06）──
    resumed: bool = False          # 是否是恢复运行
    # ── 结局 ──
    outcome: str = "completed"     # completed/truncated/failed/awaiting_approval
    elapsed: float = 0.0
    # ── 告警（阈值触发）──
    alerts: list[str] = field(default_factory=list)


# ── 阈值告警配置 ────────────────────────────────────────────
ALERT_THRESHOLDS = {
    "steps_high": 25,           # 步数超过 → 疑似卡死
    "budget_ratio_high": 0.9,   # 预算用 90% → 超支预警
    "degraded_high": 2,         # 降级子题 ≥2 → 检索质量预警
    "loops_high": 1,            # 循环刹车 ≥1 → 打转预警
}


def build_summary(state: dict, run_id: str = "", thread_id: str = "",
                  topic: str = "", elapsed: float = 0.0,
                  resumed: bool = False) -> RunSummary:
    """从最终 State 构建体检报告。"""
    s = RunSummary(
        run_id=run_id, thread_id=thread_id, topic=topic, elapsed=elapsed,
        resumed=resumed,
    )

    # L01 步数
    s.total_steps = state.get("step_count", 0) or 0
    # 循环刹车次数（从 action_history 推断：检测到循环触发截断）
    s.loop_brakes = 1 if (state.get("truncated") and "循环" in str(state.get("feedback", ""))) else 0

    # L02 成本
    s.total_tokens = state.get("token_usage", 0) or 0
    budget = settings.max_budget_tokens if settings.enable_cost_budget else 0
    s.budget_ratio = (s.total_tokens / budget) if budget > 0 else 0.0
    s.cost_mode = state.get("cost_mode", "normal") or "normal"

    # L03 降级
    s.degraded_subtopics = len(state.get("failed_subtopics", []) or [])
    # 熔断器状态（从 breaker 注册表查）
    try:
        from .breaker import all_breakers_summary
        breakers = all_breakers_summary()
        s.breaker_tripped = any(b["state"] == "open" for b in breakers)
    except Exception:
        pass

    # L04/L05 副作用
    pr = state.get("publish_result", {}) or {}
    s.published = bool(pr.get("published") or pr.get("idempotent_replay"))
    s.publish_replayed = bool(pr.get("idempotent_replay"))
    s.approval_rejected = bool(pr.get("rejected"))
    s.approval_waited = settings.enable_hitl and not s.approval_rejected

    # L06 恢复
    s.resumed = resumed

    # 结局分类
    if s.approval_rejected or state.get("truncated"):
        s.outcome = "truncated"
    else:
        s.outcome = "completed"

    # 阈值告警
    s.alerts = _check_alerts(s)
    return s


def _check_alerts(s: RunSummary) -> list[str]:
    """检查阈值，触发告警。"""
    alerts = []
    if s.total_steps >= settings.alert_steps_high:
        alerts.append(f"⚠️ 步数过高（{s.total_steps}），疑似卡死或低效")
    if s.budget_ratio >= settings.alert_budget_ratio_high:
        alerts.append(f"⚠️ 预算将耗尽（{s.budget_ratio:.0%}），超支风险")
    if s.degraded_subtopics >= settings.alert_degraded_high:
        alerts.append(f"⚠️ 降级子题多（{s.degraded_subtopics}），检索质量预警")
    if s.loop_brakes >= ALERT_THRESHOLDS["loops_high"]:
        alerts.append(f"⚠️ 触发循环刹车（{s.loop_brakes}次），打转预警")
    if s.breaker_tripped:
        alerts.append("⚠️ 熔断器打开过，工具持续故障")
    return alerts


def format_summary_line(s: RunSummary) -> str:
    """格式化为一行（日志友好）。"""
    icon = {"completed": "✅", "truncated": "🟡", "failed": "❌",
            "awaiting_approval": "⏸️"}.get(s.outcome, "?")
    line = (
        f"{icon} [{s.outcome}] run={s.run_id} steps={s.total_steps} "
        f"tokens={s.total_tokens}({s.budget_ratio:.0%}) mode={s.cost_mode} "
        f"degraded={s.degraded_subtopics} breaker={'on' if s.breaker_tripped else 'off'} "
        f"published={'Y' if s.published else 'N'}{'(replay)' if s.publish_replayed else ''} "
        f"approval={'rejected' if s.approval_rejected else ('waited' if s.approval_waited else '-')} "
        f"resumed={'Y' if s.resumed else 'N'} {s.elapsed:.1f}s"
    )
    if s.alerts:
        line += " | " + "; ".join(s.alerts)
    return line


def emit_summary(s: RunSummary):
    """输出体检报告（结构化 WARNING 若有告警，否则 INFO）。"""
    line = format_summary_line(s)
    if s.alerts:
        log.warning(line)
        for a in s.alerts:
            log.warning(f"  告警：{a}")
    else:
        log.info(line)
