"""L00 · 全景与基线：Agent 生产化的独特风险
==================================================

本脚本做两件事：
    1. 对「现状 research-assistant 的一个简化轨迹模型」注入六类故障，
       诚实记录每类故障的裸奔结局（存档 baseline_chaos.json）。
    2. 跑一次纯净跑（无故障），证明注入器本身不干扰正常流程。

为什么用「轨迹模型」而不是直接跑真实 research-assistant：
    - 真实图依赖 ChatZhipuAI（要 API key）、DuckDuckGo（要联网），
      无法满足「全离线可复现」的课程硬约束。
    - 我们要演示的是「故障怎么让 Agent 失控」的**结构性结论**——
      现状系统的缺口（无预算刹车、降级不诚实、副作用无门控、崩溃全重跑）
      与用真实 LLM 还是 mock LLM 无关。
    - 简化模型忠实复刻了现状图的关键拓扑与缺口：
        split → researcher×N(并行) → summarize → writer → reviewer ─(打回)→ writer
      以及现状的局部限位（max_rewrites / search_timeout / recursion_limit）。

诚实标注：
    - mock 下的 token 数为字符数/4 估算（非真实 API 的 usage_metadata）。
    - 结构性结论（「无预算→不刹车」「降级字符串混进材料」）与真实 API 一致。
    - L00 只读现状、不修现状；每类故障的「after」修复见后续课程。

跑法（零外部依赖）：
    python code.py
环境要求：
    Python 3.10+，标准库即可（asyncio / json / hashlib / sys）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Windows 控制台默认 GBK，print 中文会乱码；统一改成 utf-8（课程硬约束）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 把 eval_agent/chaos.py 纳入 import 路径（课程在仓库根/课程目录跑都能找到）
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "portfolio-projects" / "research-assistant"))

from eval_agent.chaos import (  # noqa: E402
    CHAOS_FAULTS, OUTCOMES, CRASH_AT_NODE,
    slow_search_factory, flaky_search_factory, loop_inducing_search_factory,
    budget_bomb_search_factory, make_publish_action, PublishLedger,
    should_crash_here,
)


# ════════════════════════════════════════════════════════════
# Part 1 · 现状系统的简化轨迹模型（忠实复刻缺口，不引真实依赖）
# ════════════════════════════════════════════════════════════

# 现状的局部限位（直接搬 config.py 的默认值，证明「不是没有限位」）
MAX_REWRITES = 3          # reviewer 打回 writer 的上限
MAX_RE_RESEARCH = 2       # 事实冲突补研上限
NUM_SUBTOPICS = 3         # 并行研究员数
SEARCH_TIMEOUT = 15       # 单次搜索超时（秒）
RECURSION_LIMIT = 25      # langgraph 默认（现状未显式配置，这是默认值）


@dataclass
class RunResult:
    """一次运行的结局档案。"""
    scenario: str                    # pure / slow / flaky / loop / crash / bomb / sideeffect
    label: str                       # 中文标签
    outcome: str                     # stuck/polluted/overspent/full_rerun/duplicate/caught
    outcome_desc: str
    total_steps: int                 # 实际跑了多少步
    total_tokens: int                # 累计 token（字符/4 估算）
    report_has_failure_string: bool  # 报告里是否混入了「超时/失败」字符串（污染证据）
    publish_count: int               # 发布动作执行次数（副作用证据）
    rerun_cost_factor: float         # 重做成本倍数（崩溃恢复相关，1.0=没重跑）
    notes: str                       # 诚实备注
    elapsed: float = 0.0             # 实际耗时（秒）


def estimate_tokens(text: str) -> int:
    """诚实估算：token ≈ 字符数/4（中英混合的粗略近似，标注为「估算」）。"""
    return max(1, len(text) // 4)


async def _run_trajectory(
    scenario: str,
    search_fn,
    publish_fn=None,
    crash_at_writer: bool = False,
    crash_after_step: int | None = None,
) -> RunResult:
    """模拟一次 research-assistant 运行的轨迹（复刻现状缺口）。

    拓扑：split(1) → researcher×NUM_SUBTOPICS(并行) → summarize(1) → writer(1)
          → reviewer(1) ─打回→ writer ... 直到 max_rewrites 或 pass。

    关键：现状系统在这里暴露的缺口——
        - 无全局步数预算（只有局部 max_rewrites，但子图并行 + 补研会叠乘）
        - 无成本刹车（token 一直累加，烧穿不停）
        - 降级不诚实（搜索超时/失败的字符串直接进材料）
        - 副作用无门控（publish 每次走到都执行）
        - 崩溃=全部重跑（没有 checkpoint 续跑语义）
    """
    t0 = time.time()
    tokens = 0
    steps = 0
    trace: list[dict] = []
    findings: list[str] = []
    report = ""
    publish_count = 0
    crashed = False

    def _step(node: str, inp: str, out: str):
        nonlocal steps, tokens
        steps += 1
        tokens += estimate_tokens(inp) + estimate_tokens(out)
        trace.append({"step": steps, "node": node, "input": inp[:200], "output": out[:200]})

    try:
        # ── split ──
        subtopics = [f"子题{i+1}" for i in range(NUM_SUBTOPICS)]
        _step("split", "研究主题", "\n".join(subtopics))

        # ── researcher×N（并行）── 每个调一次 search_fn
        async def one_researcher(sub: str) -> str:
            nonlocal tokens
            try:
                # 现状：search_timeout 在 web_search 内部 wait_for 打断
                result = await asyncio.wait_for(
                    search_fn(sub), timeout=SEARCH_TIMEOUT
                )
            except asyncio.TimeoutError:
                # 现状 web_search 的超时兜底：返回超时字符串（不诚实降级）
                result = f"搜索 '{sub}' 超时（{SEARCH_TIMEOUT}s）。可换关键词或稍后重试。"
            except Exception as e:
                # 现状 web_search 的异常兜底：返回失败字符串
                result = f"搜索 '{sub}' 失败（{type(e).__name__}: {e}）。可换关键词重试。"
            tokens += estimate_tokens(result)
            return result

        raw_findings = await asyncio.gather(*[one_researcher(s) for s in subtopics])
        for sub, f in zip(subtopics, raw_findings):
            _step("researcher", sub, f)
            findings.append(f)

        # ── summarize ──
        summary = "\n".join(findings)[:300]
        _step("summarize", "\n".join(findings), summary)

        # ── 崩溃注入点（writer 前）──
        if crash_at_writer:
            crashed = True
            # 现状：进程被杀，没有 checkpoint 续跑语义 → 全部重跑
            # 模拟「重跑一次」的成本
            rerun_tokens = tokens
            rerun_steps = steps
            # 重跑一遍 split + researcher（演示重做量无界）
            for sub in subtopics:
                try:
                    r = await asyncio.wait_for(search_fn(sub), timeout=SEARCH_TIMEOUT)
                except Exception:
                    r = "重跑搜索失败"
                rerun_tokens += estimate_tokens(r)
                rerun_steps += 1
            return RunResult(
                scenario=scenario, label=CHAOS_FAULTS.get(scenario, scenario),
                outcome="full_rerun", outcome_desc=OUTCOMES["full_rerun"],
                total_steps=rerun_steps, total_tokens=rerun_tokens,
                report_has_failure_string=False, publish_count=0,
                rerun_cost_factor=round(rerun_tokens / max(tokens, 1), 2),
                notes="崩溃在 writer 节点；现状无 checkpoint 续跑，重跑全程（重做量≈×2）",
                elapsed=round(time.time() - t0, 2),
            )

        # ── writer + reviewer 打回循环（复刻 review_route）──
        rewrites = 0
        review_pass = False
        # 循环诱导场景：reviewer 永远打回直到 max_rewrites
        force_reject = (scenario == "loop")
        # 副作用场景：reviewer 打回一次再过（演示打回→重写→重复发布）
        reject_once = (scenario == "sideeffect")
        while rewrites < MAX_REWRITES:
            _step("writer", summary, report or "（初稿）")
            # 副作用：每次 writer 后若开了 publish，都执行一次（裸奔基线）
            if publish_fn is not None:
                pub = await publish_fn("thread-1", report or summary)
                publish_count += 1
            if force_reject and rewrites < MAX_REWRITES - 1:
                decision = "rework"  # 循环诱导：永远打回
            elif reject_once and rewrites == 0:
                decision = "rework"  # 副作用：打回一次（演示重复发布）
            else:
                decision = "pass"
            _step("reviewer", report or summary, decision)
            if decision == "pass":
                review_pass = True
                break
            rewrites += 1
            report = f"第{rewrites+1}版报告"

        report = report or "最终报告"

    except Exception as e:
        # 现状：跑到 recursion_limit 抛 GraphRecursionError（崩溃式，非诚实收尾）
        return RunResult(
            scenario=scenario, label=CHAOS_FAULTS.get(scenario, scenario),
            outcome="stuck", outcome_desc=OUTCOMES["stuck"],
            total_steps=steps, total_tokens=tokens,
            report_has_failure_string=False, publish_count=publish_count,
            rerun_cost_factor=1.0,
            notes=f"跑到上限崩溃（{type(e).__name__}）——现状是 recursion_limit 硬崩",
            elapsed=round(time.time() - t0, 2),
        )

    # ── 结局判定 ──
    # 污染：报告/材料里混入了失败字符串
    material = "\n".join(findings) + report
    has_failure_str = any(kw in material for kw in ["超时", "失败（", "Not Found", "建设中"])

    if scenario == "bomb":
        outcome, desc = "overspent", OUTCOMES["overspent"]
    elif scenario == "sideeffect" and publish_count > 1:
        outcome, desc = "duplicate", OUTCOMES["duplicate"]
    elif has_failure_str:
        outcome, desc = "polluted", OUTCOMES["polluted"]
    elif scenario == "slow":
        # 慢工具被 timeout 兜住，但返回的超时字符串污染了材料
        outcome, desc = ("polluted", OUTCOMES["polluted"]) if has_failure_str else ("caught", OUTCOMES["caught"])
    elif scenario == "pure":
        outcome, desc = "caught", OUTCOMES["caught"]
    else:
        outcome, desc = "caught", OUTCOMES["caught"]

    return RunResult(
        scenario=scenario, label=CHAOS_FAULTS.get(scenario, scenario),
        outcome=outcome, outcome_desc=desc,
        total_steps=steps, total_tokens=tokens,
        report_has_failure_string=has_failure_str, publish_count=publish_count,
        rerun_cost_factor=1.0,
        notes=_scenario_note(scenario, has_failure_str, publish_count),
        elapsed=round(time.time() - t0, 2),
    )


def _scenario_note(scenario: str, polluted: bool, pub_count: int) -> str:
    if scenario == "pure":
        return "纯净跑：无故障，正常产出（证明注入器不干扰）"
    if scenario == "slow":
        return "慢工具被 search_timeout(15s) 兜住未卡死，但超时字符串混进材料→污染"
    if scenario == "flaky":
        return "坏工具：抛错被 catch，但垃圾内容混进材料→污染（更隐蔽）"
    if scenario == "loop":
        return "循环诱导：reviewer 打回到 max_rewrites 才停，局部限位兜住但步数叠乘"
    if scenario == "bomb":
        return "预算炸弹：无成本刹车，token 烧穿不停（mock 估算值，结构结论同真实）"
    if scenario == "sideeffect":
        return f"副作用无门控：发布被执行 {pub_count} 次（打回重写导致重复发布）"
    return ""


# ════════════════════════════════════════════════════════════
# Part 2 · 六类故障的裸基线跑批
# ════════════════════════════════════════════════════════════

async def run_baseline_suite() -> list[RunResult]:
    """对六类故障 + 纯净跑各跑一次，返回结局档案列表。"""
    # 一个「正常搜索」替身（纯净跑用）
    async def good_search(query, max_results=None):
        return f"[{query}] 这是关于该子题的正常搜索结果，包含若干要点和来源。"
    # 循环诱导场景需要一个「永远打回」的 publish（演示重复执行）
    ledger = PublishLedger()
    pub = make_publish_action(ledger)

    scenarios = [
        ("pure",       good_search, None, False),
        ("slow",       slow_search_factory(good_search, hang_seconds=20.0), None, False),
        ("flaky",      flaky_search_factory(good_search, error_rate=0.5), None, False),
        ("loop",       loop_inducing_search_factory(good_search), None, False),
        ("crash",      good_search, None, True),
        ("bomb",       budget_bomb_search_factory(good_search, bomb_chars=40000), None, False),
        ("sideeffect", good_search, pub, False),
    ]

    results = []
    for scenario, search_fn, publish_fn, crash in scenarios:
        # slow 场景的 hang 会被 search_timeout 打断，但要把整个 wait_for 跑完才能观察
        # 这里 hang=20 > timeout=15，所以 wait_for 会在 15s 处超时——
        # 为了不让基线跑批花 15s，把 search_timeout 临时调小（只影响演示耗时，不影响结论）
        global SEARCH_TIMEOUT
        if scenario == "slow":
            SEARCH_TIMEOUT = 1  # 演示用 1s 超时（结论不变：超时字符串会污染）
        res = await _run_trajectory(scenario, search_fn, publish_fn, crash)
        if scenario == "slow":
            SEARCH_TIMEOUT = 15  # 恢复
        results.append(res)
    return results


# ════════════════════════════════════════════════════════════
# Part 3 · 打印 + 存档
# ════════════════════════════════════════════════════════════

OUTCOME_ICON = {
    "stuck": "💀", "polluted": "☠️", "overspent": "💸",
    "full_rerun": "🔄", "duplicate": "⚠️", "caught": "✅",
}


def print_report(results: list[RunResult]):
    print()
    print("=" * 72)
    print("  AgentOps L00 · 混沌裸基线 —— 六类故障的失控结局")
    print("=" * 72)
    print(f"{'场景':<14} {'结局':<8} {'步数':>5} {'token(估)':>10} "
          f"{'污染':>5} {'发布次':>6} {'耗时(s)':>8}")
    print("-" * 72)
    for r in results:
        icon = OUTCOME_ICON.get(r.outcome, "?")
        print(f"{r.scenario:<14} {icon} {r.outcome:<7} {r.total_steps:>5} "
              f"{r.total_tokens:>10} {'是' if r.report_has_failure_string else '否':>5} "
              f"{r.publish_count:>6} {r.elapsed:>8.2f}")
    print("-" * 72)
    print()
    print("逐类诊断（诚实记录现状缺口）：")
    print("-" * 72)
    for r in results:
        if r.scenario == "pure":
            continue
        icon = OUTCOME_ICON.get(r.outcome, "?")
        print(f"  {icon} {r.label}")
        print(f"     结局：{r.outcome_desc}")
        print(f"     备注：{r.notes}")
        print()


def save_baseline(results: list[RunResult]):
    """存档 baseline_chaos.json（后续课程对照）。"""
    out_dir = _HERE
    payload = {
        "course": "agent-ops-lessons",
        "lesson": "L00",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "honesty_note": "mock 模式下 token 为字符/4 估算；"
                        "结构性结论（无预算不刹车/降级污染/副作用重放/崩溃全重跑）与真实 API 一致",
        "current_local_limits": {
            "max_rewrites": MAX_REWRITES,
            "max_re_research": MAX_RE_RESEARCH,
            "num_subtopics": NUM_SUBTOPICS,
            "search_timeout": 15,
            "recursion_limit": RECURSION_LIMIT,
        },
        "scenarios": [asdict(r) for r in results],
    }
    path = out_dir / "baseline_chaos.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n📦 基线档案已存：{path}")
    return path


async def main():
    print("=" * 72)
    print("  L00 · Agent 生产风险地图 + 混沌裸基线")
    print("=" * 72)
    print()
    print("本脚本演示：现状 research-assistant 在六类故障下的裸奔结局。")
    print("现状已有的局部限位（max_rewrites=3 / search_timeout=15s / recursion_limit=25）")
    print("诚实记录它们兜住了什么、没兜住什么。")
    print()
    print("注入的六类故障（来自 eval_agent/chaos.py）：")
    for desc in CHAOS_FAULTS.values():
        print(f"  · {desc}")
    print()

    results = await run_baseline_suite()
    print_report(results)
    save_baseline(results)

    # 诚实总结
    print()
    print("=" * 72)
    print("  基线结论：五种失控，现状的爆炸半径全是「无界」")
    print("=" * 72)
    fails = [r for r in results if r.scenario != "pure" and r.outcome != "caught"]
    for r in fails:
        icon = OUTCOME_ICON.get(r.outcome, "?")
        print(f"  {icon} {r.outcome_desc}")
    print()
    print("  纯净跑（无故障）结局：", end="")
    pure = next((r for r in results if r.scenario == "pure"), None)
    if pure:
        print(f"{OUTCOME_ICON.get(pure.outcome)} {pure.outcome_desc} —— 注入器不干扰正常流程")


if __name__ == "__main__":
    asyncio.run(main())
