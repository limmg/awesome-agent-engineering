"""
Lesson 11 — 压测与并发：找到你的 QPS 天花板
==============================================
本脚本【零外部依赖】实现一个压测器核心 + mock server，演示：
    ① 并发发请求 + 收集延迟
    ② 算 QPS / P50 / P95 / P99 / 错误率
    ③ 不同并发数下的拐点（延迟飙升 / 错误率上升）

mock server 模拟「并发越高延迟越长、超过容量就报错」的特性，
让压测曲线像真实 LLM 服务（瓶颈随并发暴露）。
落地版（loadtest/run_loadtest.py）把 mock 换成真实 kb-qa，逻辑同构。

运行：python code.py
依赖：仅标准库
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
from typing import Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# 1. mock server：模拟「并发越高越慢、超容量报错」的 LLM 服务
# ════════════════════════════════════════════════════════════════
class MockLLMServer:
    """模拟一个有容量上限的服务：基础延迟 + 并发惩罚 + 超容量报错。

    capacity=5 → 同时最多 5 个请求正常；第 6 个开始排队变慢；
    并发 > 8 → 部分请求「超时」（模拟上游 429）。
    """

    def __init__(self, base_latency: float = 0.3, capacity: int = 5) -> None:
        self.base_latency = base_latency
        self.capacity = capacity
        self._in_flight = 0

    async def handle(self, query: str) -> tuple[bool, float]:
        """处理一个请求。返回 (成功, 延迟秒)。模拟并发惩罚。"""
        self._in_flight += 1
        try:
            # 并发惩罚：超过 capacity 后，每多一个并发 +50ms
            overload = max(0, self._in_flight - self.capacity)
            latency = self.base_latency + overload * 0.05
            # 严重过载（>capacity*1.6）→ 模拟 30% 超时错误
            if self._in_flight > self.capacity * 1.6:
                await asyncio.sleep(latency)
                if (self._in_flight * 7) % 10 < 3:  # 伪随机 30%
                    return False, latency
            await asyncio.sleep(latency)
            return True, latency
        finally:
            self._in_flight -= 1


# ════════════════════════════════════════════════════════════════
# 2. 压测器：并发发请求 + 统计指标
# ════════════════════════════════════════════════════════════════
async def run_loadtest(
    handler: Callable,
    concurrency: int,
    total_requests: int,
) -> dict:
    """用 concurrency 个并发，发 total_requests 个请求，统计指标。

    返回 {qps, p50, p95, p99, error_rate, total, concurrency}。
    """
    latencies: list[float] = []
    errors = 0
    completed = 0
    sem = asyncio.Semaphore(concurrency)
    start = time.perf_counter()

    async def one_request():
        nonlocal errors, completed
        async with sem:
            ok, latency = await handler("test question")
            latencies.append(latency)
            if not ok:
                errors += 1
            completed += 1

    # 一次性派发所有任务，由 semaphore 控制并发
    await asyncio.gather(*(one_request() for _ in range(total_requests)))

    elapsed = time.perf_counter() - start
    latencies.sort()
    n = len(latencies)

    def percentile(p: float) -> float:
        idx = min(n - 1, int(n * p))
        return latencies[idx]

    return {
        "concurrency": concurrency,
        "total": total_requests,
        "qps": round(completed / elapsed, 1) if elapsed > 0 else 0,
        "p50": round(percentile(0.50) * 1000),
        "p95": round(percentile(0.95) * 1000),
        "p99": round(percentile(0.99) * 1000),
        "error_rate": round(errors / completed * 100, 1) if completed else 0,
        "elapsed": round(elapsed, 2),
    }


# ════════════════════════════════════════════════════════════════
# 3. main：不同并发数压测，找拐点
# ════════════════════════════════════════════════════════════════
async def main() -> None:
    server = MockLLMServer(base_latency=0.3, capacity=5)
    TOTAL = 60  # 每个并发档发 60 个请求

    print("=" * 78)
    print("压测 mock LLM 服务（base_latency=300ms, capacity=5 并发）")
    print("=" * 78)
    print(f"\n{'并发':<6} {'QPS':<8} {'P50(ms)':<10} {'P95(ms)':<10} "
          f"{'P99(ms)':<10} {'错误率':<8} 说明")
    print("-" * 78)

    for c in [1, 3, 5, 8, 12]:
        r = await run_loadtest(server.handle, concurrency=c, total_requests=TOTAL)
        # 解读拐点
        if r["error_rate"] > 0:
            note = "🔴 错误率上升，已达容量上限"
        elif r["p95"] > 800:
            note = "🟡 P95 飙升，接近瓶颈"
        elif c <= server.capacity:
            note = "🟢 正常区间"
        else:
            note = "🟡 超容量但还能扛（排队）"
        print(f"{r['concurrency']:<6} {r['qps']:<8} {r['p50']:<10} {r['p95']:<10} "
              f"{r['p99']:<10} {r['error_rate']}%{'':<3} {note}")

    print("\n" + "=" * 78)
    print("📊 解读：")
    print("  - 并发 1~5：QPS 随并发线性涨（容量内，正常）")
    print("  - 并发 >5：开始排队，P50/P95 上升（容量饱和）")
    print("  - 并发 12：错误率飙升 → 这就是上游限流的拐点！")
    print("  → 真实 kb-qa 同理：瓶颈在智谱 API，压到某并发错误率就涨")
    print("  → 应对：用 Semaphore 把并发卡在拐点以内，保护上游")


if __name__ == "__main__":
    asyncio.run(main())
