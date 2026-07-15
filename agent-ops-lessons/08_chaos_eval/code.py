"""L08 · 可靠性评估：混沌收益矩阵与 SLO
==================================================

本脚本调用 eval_agent/run_chaos_eval.py，对六类故障 ×（全关/全开）跑批，
输出混沌收益矩阵 + 可靠性 SLO 卡，对照 L00 baseline_chaos.json 裸基线。

核心认知：可靠性 SLO 区别于 frontier-L09 的能力收益——
    - frontier 量「干净跑下的能力」（加记忆好多少）
    - 本课量「故障注入下的生存」（断网/慢工具/崩溃下还能不能出结果）

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
_RA = _REPO / "portfolio-projects" / "research-assistant"
sys.path.insert(0, str(_RA))
sys.path.insert(0, str(_RA / "src"))
sys.path.insert(0, str(_RA / "eval_agent"))

import run_chaos_eval  # noqa: E402


def demo_slo_definition():
    print("=" * 64)
    print("  Part 1 · 可靠性 SLO 定义（区别于能力收益）")
    print("=" * 64)
    print()
    print("  ┌────────────────────────┬──────────────────────────────────┐")
    print("  │ SLO 指标                │ 含义                              │")
    print("  ├────────────────────────┼──────────────────────────────────┤")
    print("  │ 任务成功率              │ 含诚实截断算部分成功              │")
    print("  │ 卡死率                  │ 跑到 recursion_limit 崩的比例     │")
    print("  │ 预算超支率              │ token 烧穿 max_budget 的比例      │")
    print("  │ 副作用重复率            │ publish 被执行 >1 次的比例        │")
    print("  │ 崩溃恢复成功率          │ 崩溃后续跑能完成的比例            │")
    print("  │ 故障下平均浪费 token    │ 重做/超支/污染的 token            │")
    print("  └────────────────────────┴──────────────────────────────────┘")
    print()
    print("  💡 与 frontier-L09 的区别：")
    print("     frontier 量「能力」（加记忆好多少，干净跑下测）")
    print("     本课量「生存」（故障下还能不能出结果，混沌注入下测）")


def main():
    print("L08 · 可靠性评估 —— 混沌收益矩阵与 SLO")
    print()
    demo_slo_definition()
    print("\n" + "=" * 64)
    print("  Part 2 · 跑混沌收益矩阵（对照 L00 基线）")
    print("=" * 64)
    print()
    # 直接调 run_chaos_eval 的 main
    run_chaos_eval.main()


if __name__ == "__main__":
    main()
