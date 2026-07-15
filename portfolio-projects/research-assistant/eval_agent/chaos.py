"""混沌任务集：六类故障注入器（AgentOps L00 基线命根子）。

为什么自己写而不是引 chaos-toolkit：
    - 故障注入器本质就是「把真实工具/LLM 包一层 wrapper，按剧本演故障」
    - 几十行的事，写出来才懂每种故障的形态；引重依赖反而把机制藏进黑盒
    - 全离线可复现（mock LLM + mock 搜索 + 注入器），不依赖真实 API

六类故障（对应任务书 1.7）：
    ① 慢工具   web_search 挂起 30s+（超过 search_timeout）
    ② 坏工具   搜索随机抛错 / 返回垃圾内容
    ③ 循环诱导 搜索结果永远暗示「信息不足」+ reviewer 永远打回（叠加局部限位）
    ④ 进程崩溃 跑到 writer 节点时进程被杀（subprocess 注入）
    ⑤ 预算炸弹 某子题返回超长文本，token 消耗爆炸
    ⑥ 危险副作用 报告发布动作在无门控下被重复执行/未经批准执行

设计：每个注入器是一个可组合的 wrapper（函数装饰器 / callable 替换），
互不依赖、可独立开关、可叠加（例如「慢工具 + 坏工具」一起注入）。

运行结果分类（基线要诚实记录每类故障的结局）：
    - 卡死        进程挂起到 recursion_limit 才崩（GraphRecursionError）
    - 污染        失败字符串/垃圾内容混进材料被当事实写进报告
    - 超支        token 烧穿预算无刹车
    - 全部重跑    崩溃后从头来（重做量无界）
    - 重复执行    副作用被重放（重复发布）
    - 兜住        现有局部限位（max_rewrites/search_timeout 等）挡住了
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ────────────────────────────────────────────────────────────
# 注入器基座：把一个 async callable 包成「按剧本演故障」的版本
# ────────────────────────────────────────────────────────────

@dataclass
class InjectionStats:
    """注入器运行统计（跑完后看注入器演了几次故障、耗时多少）。"""
    name: str
    calls: int = 0               # 被包装函数实际被调了几次
    injected: int = 0            # 其中注入了几次故障
    total_delay: float = 0.0     # 慢工具注入累计挂起秒数
    errors_raised: int = 0       # 抛错次数
    garbage_returned: int = 0    # 返回垃圾内容次数


# ────────────────────────────────────────────────────────────
# ① 慢工具：让 web_search 挂起 30s+（超过 search_timeout=15s）
# ────────────────────────────────────────────────────────────

def slow_search_factory(real_search: Callable, hang_seconds: float = 30.0):
    """返回一个「永远挂起 hang_seconds 秒」的 web_search 替身。

    现状系统的 search_timeout=15s 会在 15s 处打断它，返回超时字符串。
    但 hang_seconds 设大一点能保证「确实超过了超时阈值」，演示更稳定。
    （基线观察：超时字符串混进材料 → 污染，不是「卡死」）
    """
    stats = InjectionStats(name="slow_search")

    async def slow_search(query: str, max_results: int | None = None) -> str:
        stats.calls += 1
        stats.injected += 1
        stats.total_delay += hang_seconds
        # 模拟一个真的挂起的网络请求（会被 asyncio.wait_for 在 timeout 处打断）
        await asyncio.sleep(hang_seconds)
        return f"[慢工具] {query} 的搜索结果（实际上 await 会被 timeout 打断，到不了这）"

    slow_search.stats = stats  # type: ignore[attr-defined]
    return slow_search


# ────────────────────────────────────────────────────────────
# ② 坏工具：随机抛错 / 返回垃圾内容
# ────────────────────────────────────────────────────────────

def flaky_search_factory(real_search: Callable, error_rate: float = 0.5,
                         seed: int = 42):
    """返回一个「一半概率抛错、一半概率吐垃圾」的 web_search 替身。

    error_rate: 抛错概率；剩下的返回垃圾内容（看起来像结果但是无意义文本）。
    基线观察：现状系统 catch 了异常返回失败字符串，但「垃圾内容」会被
    当成正常结果混进材料 → 污染（这是更隐蔽的故障形态）。
    """
    stats = InjectionStats(name="flaky_search")
    rng = random.Random(seed)
    garbage = [
        "相关信息请咨询当地相关部门。",
        "据某不知名来源透露，情况十分复杂，需要进一步确认。",
        "本页面正在建设中，敬请期待。",
        "404 Not Found —— 你寻找的内容不存在。",
    ]

    async def flaky_search(query: str, max_results: int | None = None) -> str:
        stats.calls += 1
        stats.injected += 1
        if rng.random() < error_rate:
            stats.errors_raised += 1
            raise ConnectionError(f"[坏工具] 搜索 {query} 时连接被重置（注入错误）")
        stats.garbage_returned += 1
        return rng.choice(garbage)

    flaky_search.stats = stats  # type: ignore[attr-defined]
    return flaky_search


# ────────────────────────────────────────────────────────────
# ③ 循环诱导：搜索结果永远暗示「信息不足需再查」+ reviewer 永远打回
# ────────────────────────────────────────────────────────────

def loop_inducing_search_factory(real_search: Callable):
    """返回一个「永远暗示信息不足」的 web_search 替身。

    每次搜索都返回「该领域发展迅速，现有资料不足以全面覆盖，建议补充检索」——
    诱导 researcher 觉得「还没查够」，诱导 reviewer 觉得「研究不充分」打回。
    叠加现状的 max_rewrites=3 × max_re_research=2 × num_subtopics=3，
    把所有局部限位拉满，看总步数是否仍然无界（基线结论：是）。
    """
    stats = InjectionStats(name="loop_inducing_search")
    hints = [
        "该领域发展迅速，现有资料不足以全面覆盖，建议补充检索最新进展。",
        "现有结果存在争议，需要更多来源交叉验证，建议继续查询。",
        "信息覆盖不完整，关键细节缺失，建议针对子问题深入检索。",
    ]

    async def looping_search(query: str, max_results: int | None = None) -> str:
        stats.calls += 1
        stats.injected += 1
        return f"[{query}] {hints[stats.calls % len(hints)]}"

    looping_search.stats = stats  # type: ignore[attr-defined]
    return looping_search


# ────────────────────────────────────────────────────────────
# ⑤ 预算炸弹：某子题返回超长文本，token 消耗爆炸
# ────────────────────────────────────────────────────────────

def budget_bomb_search_factory(real_search: Callable, bomb_chars: int = 50000):
    """返回一个「吐超长文本」的 web_search 替身。

    每次返回 bomb_chars 字符的填充文本——模拟某个搜索结果是一篇巨长文档。
    基线观察：现状系统没有成本刹车，这些 token 会被 LLM 全吃下，烧穿预算。
    （mock 下 token 为估算值，但「无预算→不刹车」的结构性结论与真实 API 一致）
    """
    stats = InjectionStats(name="budget_bomb_search")

    async def bomb_search(query: str, max_results: int | None = None) -> str:
        stats.calls += 1
        stats.injected += 1
        # 吐一篇「看起来是搜索结果但巨长」的文本
        padding = "该主题涉及大量技术细节需要详尽阐述。" * (bomb_chars // 23 + 1)
        return f"[{query}] {padding[:bomb_chars]}"

    bomb_search.stats = stats  # type: ignore[attr-defined]
    return bomb_search


# ────────────────────────────────────────────────────────────
# ⑥ 危险副作用：一个会被重复执行的发布动作（无门控基线）
# ────────────────────────────────────────────────────────────

@dataclass
class PublishLedger:
    """发布注册表（演示副作用重复执行用的记账本）。

    生产环境 publish_report 应该写 sqlite + outputs/；
    这里简化成内存 list，只为了演示「重复执行了几次」这个事实。
    L04 会给真 publish 加幂等键，第二次 no-op。
    """
    publishes: list[dict] = field(default_factory=list)

    def record(self, thread_id: str, content_hash: str) -> dict:
        entry = {
            "thread_id": thread_id,
            "content_hash": content_hash,
            "ts": time.time(),
            "seq": len(self.publishes) + 1,
        }
        self.publishes.append(entry)
        return entry


def make_publish_action(ledger: PublishLedger):
    """造一个「不带任何门控」的发布动作——裸奔基线。

    每次调用都真的记录一次发布。reviewer 打回重写 → writer 重写 →
    再走到 publish = 重复发布（事故）。L04 加幂等键、L05 加审批门。
    """
    call_count = {"n": 0}

    async def publish_report(thread_id: str, content: str) -> dict:
        call_count["n"] += 1
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        entry = ledger.record(thread_id, content_hash)
        return {"published": True, "seq": entry["seq"], "call": call_count["n"]}

    publish_report.call_count = call_count  # type: ignore[attr-defined]
    return publish_report


# ────────────────────────────────────────────────────────────
# ④ 进程崩溃：subprocess 注入（在 code.py 里演示，这里只给触发点判定）
# ────────────────────────────────────────────────────────────

CRASH_AT_NODE = "writer"  # 跑到 writer 节点时杀进程


def should_crash_here(node: str, step: int, crash_at: str = CRASH_AT_NODE) -> bool:
    """进程崩溃注入的判定函数。

    真正的「杀进程」要用 subprocess（见 chaos L00 code.py），
    这里给的是「该不该在当前节点崩」的判定，供 mock 演示用。
    """
    return node == crash_at


# ────────────────────────────────────────────────────────────
# 注入器注册表：六类故障一览（code.py / L08 harness 复用）
# ────────────────────────────────────────────────────────────

CHAOS_FAULTS: dict[str, str] = {
    "slow":     "① 慢工具：web_search 挂起 30s+（超 search_timeout）",
    "flaky":    "② 坏工具：搜索随机抛错 / 返回垃圾内容",
    "loop":     "③ 循环诱导：结果永远暗示信息不足 + reviewer 永远打回",
    "crash":    "④ 进程崩溃：跑到 writer 节点时进程被杀",
    "bomb":     "⑤ 预算炸弹：子题返回超长文本，token 爆炸",
    "sideeffect": "⑥ 危险副作用：发布动作无门控被重复执行",
}


# 故障结局分类（基线档案的标准枚举）
OUTCOMES = {
    "stuck":         "卡死（挂到 recursion_limit 才崩）",
    "polluted":      "污染（失败/垃圾字符串混进材料当事实）",
    "overspent":     "超支（token 烧穿预算无刹车）",
    "full_rerun":    "全部重跑（崩溃后重做量无界）",
    "duplicate":     "重复执行（副作用被重放）",
    "caught":        "兜住（现有局部限位挡住了）",
}


if __name__ == "__main__":
    # 自检：打印六类故障清单
    print("=" * 60)
    print("混沌任务集 · 六类故障注入器")
    print("=" * 60)
    for key, desc in CHAOS_FAULTS.items():
        print(f"  {desc}")
    print()
    print("结局分类：")
    for key, desc in OUTCOMES.items():
        print(f"  {key:12s} → {desc}")
