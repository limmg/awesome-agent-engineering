"""L01 · 步数与循环：给轨迹装里程表
==================================================

本脚本演示故障③（循环诱导）的 before/after：
    - before（裸奔）：reviewer 永远打回 → 叠加局部限位仍跑到步数很大才停，
      或撞 recursion_limit 抛 GraphRecursionError（崩溃式收尾）。
    - after（开步数预算）：第 N 步触发「诚实收尾」——带着已有材料进 writer
      出部分结果（标注截断），而非 raise 崩掉。

还演示：
    - 动作签名循环检测（在线执法，复用 frontier-L08 思路）
    - 诚实收尾 vs recursion_limit 崩溃式收尾的本质区别

为什么用轨迹模型而不是真实图：
    真实图要 API key + 联网；这里要演示的是「步数预算怎么拦循环」的结构性结论，
    与真实 LLM 还是 mock 无关。模型忠实复刻了 research_team→writer→reviewer 打回循环
    + 现状的局部限位（max_rewrites）+ L01 的新机制（step_budget/loop_detect）。

跑法（零外部依赖）：
    python code.py
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 复用 L00 的混沌注入器（循环诱导）
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "portfolio-projects" / "research-assistant"))

from eval_agent.chaos import loop_inducing_search_factory  # noqa: E402


# ────────────────────────────────────────────────────────────
# 现状局部限位（搬 config.py 默认值）
# ────────────────────────────────────────────────────────────
MAX_REWRITES = 3
RECURSION_LIMIT = 25  # langgraph 默认


@dataclass
class StepBudgetConfig:
    """L01 新增开关（默认全关 = 现状行为）。"""
    enable_step_budget: bool = False
    max_total_steps: int = 8           # 演示用小值（真实默认 30）
    enable_loop_detect: bool = False
    loop_detect_window: int = 3


@dataclass
class TrajectoryRun:
    """一次打回循环运行的结局。"""
    label: str
    outcome: str            # "recursion_crash" / "honest_truncate" / "local_limit_stop"
    total_steps: int
    truncated: bool
    report_has_marker: bool  # 报告里有没有「截断」标注
    notes: str


def _signature(node: str, param: str) -> str:
    """动作签名（与 step_budget.py 一致的简化版）。"""
    import hashlib
    h = hashlib.md5(param[:80].encode("utf-8")).hexdigest()[:8]
    return f"{node}:{h}"


def _detect_loop(history: list[str], window: int) -> bool:
    if len(history) < window:
        return False
    return len(set(history[-window:])) == 1


async def run_review_loop(cfg: StepBudgetConfig, scenario: str) -> TrajectoryRun:
    """模拟 research_team→writer→reviewer 打回循环。

    循环诱导场景：search 永远暗示信息不足，reviewer 永远打回。
    看哪种限位机制先生效。
    """
    steps = 0
    history: list[str] = []
    rewrites = 0
    report = ""
    truncated = False
    crash = False

    # 循环诱导的搜索（永远暗示信息不足）
    loop_search = loop_inducing_search_factory(None)

    # 模拟一轮研究 + writer + reviewer 打回循环
    # 每轮：research_team(1步) → writer(1步) → reviewer(1步)，reviewer 打回则重来
    try:
        # 第一轮研究
        await loop_search("子题")
        steps += 1; history.append(_signature("research_team", "topic"))

        while True:
            # writer
            steps += 1; history.append(_signature("writer", f"v{rewrites+1}"))
            report = f"第{rewrites+1}版报告"

            # reviewer
            steps += 1; history.append(_signature("reviewer", "rework"))

            # ── L01 新机制检查（在 reviewer 决策前）──
            if cfg.enable_step_budget and steps >= cfg.max_total_steps:
                truncated = True
                report = f"⚠️ 因步数预算截断（{steps}/{cfg.max_total_steps}），部分结果：{report}"
                break
            if cfg.enable_loop_detect and _detect_loop(history, cfg.loop_detect_window):
                truncated = True
                report = f"⚠️ 因检测到循环截断，部分结果：{report}"
                break

            # ── 现状局部限位检查 ──
            if rewrites >= MAX_REWRITES:
                # 局部限位兜住
                break

            # 循环诱导：reviewer 永远打回
            rewrites += 1

            # 防真崩：recursion_limit 兜底（崩溃式）
            if steps >= RECURSION_LIMIT:
                crash = True
                break

    except Exception:
        crash = True

    if crash:
        return TrajectoryRun(scenario, "recursion_crash", steps, False, False,
                             f"撞 recursion_limit({RECURSION_LIMIT}) 崩溃式收尾（GraphRecursionError）")
    if truncated:
        return TrajectoryRun(scenario, "honest_truncate", steps, True, True,
                             f"步数预算/循环检测触发诚实收尾（第 {steps} 步，带部分结果退出）")
    return TrajectoryRun(scenario, "local_limit_stop", steps, False, False,
                         f"局部限位 max_rewrites={MAX_REWRITES} 兜住（步数={steps}）")


async def main():
    print("=" * 68)
    print("  L01 · 步数与循环 —— 故障③循环诱导的 before/after")
    print("=" * 68)
    print()
    print("现状局部限位：max_rewrites=3（reviewer 打回上限）")
    print("langgraph 默认 recursion_limit=25（最后保险丝，崩溃式）")
    print()

    scenarios = [
        ("before（裸奔）",
         StepBudgetConfig(enable_step_budget=False, enable_loop_detect=False)),
        ("after（开步数预算 max=8）",
         StepBudgetConfig(enable_step_budget=True, max_total_steps=8)),
        ("after（开循环检测 window=3）",
         StepBudgetConfig(enable_loop_detect=True, loop_detect_window=3)),
        ("after（步数预算 + 循环检测都开）",
         StepBudgetConfig(enable_step_budget=True, max_total_steps=8,
                          enable_loop_detect=True, loop_detect_window=3)),
    ]

    print(f"{'场景':<32} {'结局':<20} {'步数':>5} {'截断':>5} {'标注':>5}")
    print("-" * 68)
    for label, cfg in scenarios:
        r = await run_review_loop(cfg, label)
        outcome_icon = {"recursion_crash": "💀", "honest_truncate": "✅",
                        "local_limit_stop": "🟡"}[r.outcome]
        print(f"{label:<30} {outcome_icon} {r.outcome:<19} {r.total_steps:>5} "
              f"{'是' if r.truncated else '否':>5} {'是' if r.report_has_marker else '否':>5}")
    print("-" * 68)
    print()

    print("=" * 68)
    print("  逐场景诊断")
    print("=" * 68)
    for label, cfg in scenarios:
        r = await run_review_loop(cfg, label)
        outcome_icon = {"recursion_crash": "💀", "honest_truncate": "✅",
                        "local_limit_stop": "🟡"}[r.outcome]
        print(f"\n  {outcome_icon} {label}")
        print(f"     {r.notes}")
        if r.outcome == "honest_truncate":
            print(f"     报告示例：{r.report_has_marker and '⚠️ 含截断标注，带部分结果' or '无标注'}")
        elif r.outcome == "local_limit_stop":
            print(f"     局部限位兜住但步数={r.total_steps}——若叠加补研/更多子题仍会涨")
        elif r.outcome == "recursion_crash":
            print(f"     崩溃式收尾——没有部分结果，用户看到的是报错")

    print()
    print("=" * 68)
    print("  结论：两层限位的分工")
    print("=" * 68)
    print("  · 全局步数预算（L01）：细，可收尾——超 max_total_steps 带部分结果退出")
    print("  · recursion_limit（langgraph）：粗，崩溃式——最后的保险丝，不该靠它兜")
    print("  · 局部限位（max_rewrites 等）：兜各自回路，但叠乘后总步数仍可能很大")
    print("  · 循环检测（动作签名）：在线执法——事后评估能发现绕路，生产上得当场刹车")


if __name__ == "__main__":
    asyncio.run(main())
