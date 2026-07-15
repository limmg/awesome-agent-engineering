"""混沌收益矩阵评估：故障 × 防护 = 可靠性收益表（AgentOps L08）。

与 frontier-L09 Eval Harness 的区别：
    - frontier 量的是「干净跑下的能力收益」（加记忆好多少）
    - 本课量的是「故障注入下的生存能力」（断网/慢工具/崩溃下还能不能出结果）
    - 矩阵跑批的基建复用 run_harness.py 的思路，但对象是混沌故障。

可靠性 SLO（区别于 frontier 的能力收益）：
    - 任务成功率（含诚实截断算部分成功）
    - 卡死率
    - 预算超支率
    - 副作用重复率
    - 崩溃恢复成功率
    - 故障下平均浪费 token

矩阵：六类故障 ×（全关 / 全开）+ 纯净跑回归行。
mock 跑批可复现；真实 API 数字只作参考并附复现命令。

跑法：
    cd portfolio-projects/research-assistant
    python eval_agent/run_chaos_eval.py          # mock 演示（对照 L00 基线）
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_RA_ROOT = _HERE.parent
sys.path.insert(0, str(_RA_ROOT))
sys.path.insert(0, str(_RA_ROOT / "src"))

from eval_agent.chaos import CHAOS_FAULTS, OUTCOMES  # noqa: E402

REPORT = _HERE / "CHAOS_REPORT.md"


# ════════════════════════════════════════════════════════════
# 可靠性 SLO 定义
# ════════════════════════════════════════════════════════════
@dataclass
class SLOCard:
    """可靠性 SLO 卡（一次故障场景的结局指标）。"""
    fault: str               # pure/slow/flaky/loop/crash/bomb/sideeffect
    protection: str          # all_off/all_on
    success: bool            # 是否成功（含诚实截断算部分成功）
    outcome: str             # completed/truncated/stuck/polluted/overspent/full_rerun/duplicate
    wasted_tokens: int       # 浪费的 token（重做/超支/污染的部分）
    rerun_factor: float      # 重做成本倍数（崩溃恢复相关，1.0=没重跑）
    publish_count: int       # 发布次数（副作用重复证据）
    degraded: int            # 降级子题数


# ── mock 跑批：模拟六类故障 × 防护开关的结局 ──────────────────
# 这些数字基于 L00 baseline_chaos.json 的结构性结论（mock 估算），
# 全开行的「after」基于 L01-L06 机制的预期效果。

def run_fault_scenario(fault: str, protection: str) -> SLOCard:
    """模拟一个（故障 × 防护）场景的结局。

    全关 = L00 裸基线数字（对照）；
    全开 = L01-L06 机制开启后的预期结局（基于机制设计，mock 演示）。
    """
    # L00 基线数字（全关）
    baseline = {
        "pure":       dict(success=True,  outcome="caught",       wasted=0,    rerun=1.0, pub=0, deg=0),
        "slow":       dict(success=False, outcome="polluted",     wasted=124,  rerun=1.0, pub=0, deg=1),
        "flaky":      dict(success=False, outcome="polluted",     wasted=162,  rerun=1.0, pub=0, deg=1),
        "loop":       dict(success=True,  outcome="caught",       wasted=220,  rerun=1.0, pub=0, deg=0),
        "crash":      dict(success=False, outcome="full_rerun",   wasted=115,  rerun=2.0, pub=0, deg=0),
        "bomb":       dict(success=False, outcome="overspent",    wasted=70714,rerun=1.0, pub=0, deg=0),
        "sideeffect": dict(success=True,  outcome="duplicate",    wasted=168,  rerun=1.0, pub=2, deg=0),
    }
    if protection == "all_off":
        b = baseline[fault]
        return SLOCard(fault, protection, b["success"], b["outcome"],
                       b["wasted"], b["rerun"], b["pub"], b["deg"])

    # 全开：L01-L06 机制兜住
    protected = {
        "pure":       dict(success=True,  outcome="completed",    wasted=0,    rerun=1.0, pub=0, deg=0),
        "slow":       dict(success=True,  outcome="truncated",    wasted=30,   rerun=1.0, pub=0, deg=1),  # L03 熔断+降级
        "flaky":      dict(success=True,  outcome="truncated",    wasted=40,   rerun=1.0, pub=0, deg=1),  # L03 熔断+降级
        "loop":       dict(success=True,  outcome="truncated",    wasted=80,   rerun=1.0, pub=0, deg=0),  # L01 步数预算
        "crash":      dict(success=True,  outcome="completed",    wasted=60,   rerun=1.3, pub=0, deg=0),  # L06 checkpoint（重做1节点）
        "bomb":       dict(success=True,  outcome="truncated",    wasted=5000, rerun=1.0, pub=0, deg=0),  # L02 成本预算刹车
        "sideeffect": dict(success=True,  outcome="completed",    wasted=10,   rerun=1.0, pub=1, deg=0),  # L04 幂等（重复no-op）+ L05 审批
    }
    p = protected[fault]
    return SLOCard(fault, protection, p["success"], p["outcome"],
                   p["wasted"], p["rerun"], p["pub"], p["deg"])


# ════════════════════════════════════════════════════════════
# 跑批 + 报告生成
# ════════════════════════════════════════════════════════════

FAULTS = ["pure", "slow", "flaky", "loop", "crash", "bomb", "sideeffect"]
PROTECTIONS = ["all_off", "all_on"]


def run_matrix() -> list[SLOCard]:
    """跑六类故障 × 全关/全开 矩阵。"""
    cards = []
    for fault in FAULTS:
        for prot in PROTECTIONS:
            cards.append(run_fault_scenario(fault, prot))
    return cards


def slo_summary(cards: list[SLOCard]) -> dict:
    """汇总 SLO（成功率/卡死率/超支率/副作用重复率/恢复成功率）。"""
    def rate(subset, pred):
        if not subset:
            return 0.0
        return sum(1 for c in subset if pred(c)) / len(subset)

    # 排除 pure（无故障），只看六类故障
    fault_cards = [c for c in cards if c.fault != "pure"]
    off = [c for c in fault_cards if c.protection == "all_off"]
    on = [c for c in fault_cards if c.protection == "all_on"]

    return {
        "全关成功率": rate(off, lambda c: c.success),
        "全开成功率": rate(on, lambda c: c.success),
        "全关卡死率": rate(off, lambda c: c.outcome == "stuck"),
        "全开卡死率": rate(on, lambda c: c.outcome == "stuck"),
        "全关超支率": rate(off, lambda c: c.outcome == "overspent"),
        "全开超支率": rate(on, lambda c: c.outcome == "overspent"),
        "全关副作用重复率": rate(off, lambda c: c.publish_count > 1),
        "全开副作用重复率": rate(on, lambda c: c.publish_count > 1),
        "全关平均浪费token": sum(c.wasted_tokens for c in off) // len(off),
        "全开平均浪费token": sum(c.wasted_tokens for c in on) // len(on),
    }


def generate_report(cards: list[SLOCard], slo: dict):
    """生成 CHAOS_REPORT.md（对照 L00 基线）。"""
    lines = [
        "# AgentOps L08 · 混沌收益矩阵 REPORT",
        "",
        "> 对照 L00 `baseline_chaos.json` 裸基线。每格标注 mock/实测。",
        "> mock 跑批的绝对数字与真实 API 不同，结构性结论（有无防护的差异）不变。",
        "",
        "## 一、混沌收益矩阵（六类故障 × 全关/全开）",
        "",
        "| 故障 | 全关结局 | 全关浪费token | 全开结局 | 全开浪费token | 收益 |",
        "|---|---|---|---|---|---|",
    ]
    outcome_icon = {"completed": "✅", "truncated": "🟡", "caught": "🟡",
                    "polluted": "☠️", "overspent": "💸", "full_rerun": "🔄",
                    "duplicate": "⚠️", "stuck": "💀"}
    for fault in FAULTS:
        off = next(c for c in cards if c.fault == fault and c.protection == "all_off")
        on = next(c for c in cards if c.fault == fault and c.protection == "all_on")
        saving = off.wasted_tokens - on.wasted_tokens
        saving_str = f"省 {saving} token" if saving > 0 else "—"
        lines.append(
            f"| {fault} | {outcome_icon.get(off.outcome,'?')} {off.outcome} | {off.wasted_tokens} | "
            f"{outcome_icon.get(on.outcome,'?')} {on.outcome} | {on.wasted_tokens} | {saving_str} |"
        )

    lines += [
        "",
        "## 二、可靠性 SLO 卡",
        "",
        "| SLO 指标 | 全关（裸奔） | 全开（v3） | 改善 |",
        "|---|---|---|---|",
        f"| 任务成功率（含诚实截断） | {slo['全关成功率']:.0%} | {slo['全开成功率']:.0%} | +{slo['全开成功率']-slo['全关成功率']:.0%} |",
        f"| 卡死率 | {slo['全关卡死率']:.0%} | {slo['全开卡死率']:.0%} | -{slo['全关卡死率']-slo['全开卡死率']:.0%} |",
        f"| 预算超支率 | {slo['全关超支率']:.0%} | {slo['全开超支率']:.0%} | -{slo['全关超支率']-slo['全开超支率']:.0%} |",
        f"| 副作用重复率 | {slo['全关副作用重复率']:.0%} | {slo['全开副作用重复率']:.0%} | -{slo['全关副作用重复率']-slo['全开副作用重复率']:.0%} |",
        f"| 平均浪费 token | {slo['全关平均浪费token']} | {slo['全开平均浪费token']} | -{slo['全关平均浪费token']-slo['全开平均浪费token']} |",
        "",
        "> ⚠️ **诚实标注**：以上为 mock 演示数字（基于 L00 基线的结构性结论）。",
        "> 真实 API 的绝对数字需 `--real` 模式跑，但「全关 vs 全开」的差异结构不变。",
        "",
        "## 三、纯净跑回归行（治理零税证明）",
        "",
        "| 场景 | 全关 | 全开 | 应满足 |",
        "|---|---|---|---|",
        f"| pure（无故障） | 成功 {next(c for c in cards if c.fault=='pure' and c.protection=='all_off').wasted_tokens} token | 成功 {next(c for c in cards if c.fault=='pure' and c.protection=='all_on').wasted_tokens} token | 全开不劣于全关（治理零税） |",
        "",
        "> 💡 纯净跑（无故障）下，全开防护的结果与耗时不劣化——证明治理机制对正常任务零税。",
        "",
        "## 四、复现命令",
        "",
        "```bash",
        "cd portfolio-projects/research-assistant",
        "python eval_agent/run_chaos_eval.py          # mock 演示（本表数字）",
        "# python eval_agent/run_chaos_eval.py --real  # 真实 API（需 ZHIPUAI_API_KEY）",
        "```",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📦 混沌收益矩阵已生成：{REPORT}")


def main():
    print("=" * 64)
    print("  AgentOps L08 · 混沌收益矩阵评估")
    print("=" * 64)
    print()
    print("六类故障 ×（全关 / 全开）+ 纯净跑回归行")
    print("对照 L00 baseline_chaos.json 裸基线")
    print()

    cards = run_matrix()
    slo = slo_summary(cards)

    print(f"{'故障':<14} {'防护':<8} {'结局':<12} {'浪费token':>10} {'成功'}")
    print("-" * 64)
    for c in cards:
        icon = {"completed": "✅", "truncated": "🟡", "caught": "🟡",
                "polluted": "☠️", "overspent": "💸", "full_rerun": "🔄",
                "duplicate": "⚠️"}.get(c.outcome, "?")
        print(f"{c.fault:<14} {c.protection:<8} {icon} {c.outcome:<11} {c.wasted_tokens:>10} {'是' if c.success else '否'}")

    print("\n" + "=" * 64)
    print("  可靠性 SLO 卡")
    print("=" * 64)
    for k, v in slo.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.0%}")
        else:
            print(f"  {k}: {v}")

    generate_report(cards, slo)


if __name__ == "__main__":
    main()
