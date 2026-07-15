"""L07 · 轨迹级可观测：一次运行一行体检报告
==================================================

本脚本演示：对 L00 六类故障各跑一次（开对应防护），打印六行 run summary 对比——
一眼看出每类故障被哪个机制兜住、代价多少。

run summary 字段：步数/循环刹车/token与预算比/降级次数/熔断开闭/审批等待/恢复次数/结局。
与 frontier-L08 轨迹评估的区别：评估算质量指标（事后离线），观测算健康指标（实时在线）。

跑法（零外部依赖）：
    python code.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "portfolio-projects" / "research-assistant" / "src"))

from research_assistant.run_summary import (  # noqa: E402
    build_summary, format_summary_line,
)


def demo_six_faults_summary():
    """六类故障各跑一次 → 六行 summary 对比。"""
    # 模拟六类故障下（开对应防护后）的最终 state
    scenarios = [
        ("pure",   "纯净跑（无故障）",
         {"step_count": 7,  "token_usage": 142,   "failed_subtopics": [], "truncated": False,
          "publish_result": {}, "cost_mode": "normal", "feedback": ""}),
        ("slow",   "①慢工具（L03 熔断+降级）",
         {"step_count": 7,  "token_usage": 124,   "failed_subtopics": ["子题1（超时）"], "truncated": False,
          "publish_result": {}, "cost_mode": "normal", "feedback": ""}),
        ("flaky",  "②坏工具（L03 熔断+降级）",
         {"step_count": 7,  "token_usage": 162,   "failed_subtopics": ["子题1（错误）"], "truncated": False,
          "publish_result": {}, "cost_mode": "normal", "feedback": ""}),
        ("loop",   "③循环诱导（L01 步数预算）",
         {"step_count": 11, "token_usage": 220,   "failed_subtopics": [], "truncated": False,
          "publish_result": {}, "cost_mode": "normal", "feedback": ""}),
        ("crash",  "④进程崩溃（L06 checkpoint 续跑）",
         {"step_count": 8,  "token_usage": 115,   "failed_subtopics": [], "truncated": False,
          "publish_result": {}, "cost_mode": "normal", "feedback": ""}),
        ("bomb",   "⑤预算炸弹（L02 成本预算）",
         {"step_count": 7,  "token_usage": 70714, "failed_subtopics": [], "truncated": False,
          "publish_result": {}, "cost_mode": "over_budget", "feedback": ""}),
    ]

    print("=" * 80)
    print("  L07 · 六类故障各跑一次 → 六行 run summary 体检报告")
    print("=" * 80)
    print()
    print(f"{'场景':<16} {'结局':<11} {'步数':>5} {'token':>8} {'降级':>5} {'告警'}")
    print("-" * 80)
    for name, label, state in scenarios:
        s = build_summary(state, run_id=name, topic=label)
        icon = {"completed": "✅", "truncated": "🟡"}.get(s.outcome, "?")
        alert_str = "; ".join(s.alerts) if s.alerts else "—"
        print(f"{name:<16} {icon} {s.outcome:<9} {s.total_steps:>5} {s.total_tokens:>8} "
              f"{s.degraded_subtopics:>5}  {alert_str}")
    print("-" * 80)
    print()
    print("  💡 一眼看出：")
    print("     · slow/flaky 被 L03 兜住（降级声明，没污染）")
    print("     · loop 被 L01 兜住（步数有上限）")
    print("     · bomb 被 L02 触发 over_budget 模式（诚实截断）")
    print("     · pure 无告警（健康跑）")


def demo_threshold_alerts():
    """演示阈值告警。"""
    print("\n" + "=" * 80)
    print("  Part 2 · 阈值告警（超阈值打 WARNING）")
    print("=" * 80)

    bad_state = {
        "step_count": 30,           # > 25 → 步数告警
        "token_usage": 47500,       # 假设 budget=50000，95% → 超支告警
        "failed_subtopics": ["a", "b", "c"],  # 3 ≥ 2 → 降级告警
        "truncated": True, "feedback": "步数预算超限",
        "publish_result": {}, "cost_mode": "over_budget",
    }
    # 临时开 budget 让 ratio 算出来
    from research_assistant import config
    config.settings.__dict__["enable_cost_budget"] = True
    config.settings.__dict__["max_budget_tokens"] = 50000

    s = build_summary(bad_state, run_id="bad-run")
    print(f"\n  问题跑的 summary：")
    print(f"  {format_summary_line(s)}")
    print(f"\n  触发告警 {len(s.alerts)} 条：")
    for a in s.alerts:
        print(f"    {a}")
    print(f"\n  💡 这些告警在生产上接告警系统（本课落日志），不等用户投诉。")


def demo_vs_ops_request_logs():
    """演示与 ops 请求级日志的分层。"""
    print("\n" + "=" * 80)
    print("  Part 3 · 与 ops 请求级日志的分层")
    print("=" * 80)
    print()
    print("  ┌─────────────────────┬─────────────────────────────────────┐")
    print("  │ 维度                 │ 区别                                │")
    print("  ├─────────────────────┼─────────────────────────────────────┤")
    print("  │ ops-L01/L02（请求级）│ span 级日志/tracing，看「这一步」    │")
    print("  │ 本课（轨迹级）        │ 运行级聚合，看「这次跑得健康吗」      │")
    print("  │ frontier-L08（评估） │ 质量指标，事后离线批量               │")
    print("  └─────────────────────┴─────────────────────────────────────┘")
    print()
    print("  💡 翻日志是事后侦查（出事再挖），run summary 是实时体检（当场告警）。")
    print("     三层互补：请求日志看细节，run summary 看健康，评估看质量。")


def main():
    print("L07 · 轨迹级可观测 —— 一次运行一行体检报告")
    print()
    demo_six_faults_summary()
    demo_threshold_alerts()
    demo_vs_ops_request_logs()
    print("\n" + "=" * 80)
    print("  结论")
    print("=" * 80)
    print("  · run summary：步数/成本/降级/熔断/审批/恢复/结局，一行汇总")
    print("  · 阈值告警：超阈值打 WARNING，生产接告警系统，本课落日志")
    print("  · 与 frontier-L08 评估字段对齐：观测算健康（实时），评估算质量（事后）")
    print("  · 三层观测：请求日志（ops）看细节，run summary 看健康，评估看质量")


if __name__ == "__main__":
    main()
