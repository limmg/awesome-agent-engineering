"""kb-qa 压测器：自实现 asyncio 版，压 /api/ask 找 QPS 天花板（LLMOps L11）。

零新依赖（用 kb-qa 已有的 httpx），多档并发压测，产出 QPS/P50/P95/P99/错误率。
落地逻辑与 ops-lessons/11_loadtest/code.py 同构，把 mock 换成真实 kb-qa。

用法（先起服务：python -m uvicorn api.main:app --port 8001）：
    python loadtest/run_loadtest.py                              # 默认并发 1/3/5
    python loadtest/run_loadtest.py --concurrency 1 5 10 20      # 自定义并发档
    python loadtest/run_loadtest.py --api-key kb-test-123        # 带鉴权 key（L04）
    python loadtest/run_loadtest.py --requests 100               # 每档请求数
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx  # kb-qa 已装


async def hit_ask(
    client: httpx.AsyncClient,
    base_url: str,
    question: str,
    api_key: str | None,
) -> tuple[bool, float, int]:
    """发一次 /api/ask（SSE，读完整流才算完成）。返回 (成功, 延迟ms, 状态码)。

    注意：/api/ask 是 SSE 流式，要读到 done 事件才算完整响应。
    压测只关心端到端延迟（从发请求到拿到完整答案）。
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"question": question}
    t0 = time.perf_counter()
    try:
        # SSE：用 stream 读完整响应
        async with client.stream(
            "POST", f"{base_url}/api/ask", headers=headers, json=payload, timeout=60,
        ) as resp:
            if resp.status_code != 200:
                await resp.aread()
                return False, (time.perf_counter() - t0) * 1000, resp.status_code
            async for line in resp.aiter_lines():
                pass  # 读完整流（拿到 done）
        return True, (time.perf_counter() - t0) * 1000, 200
    except Exception:
        return False, (time.perf_counter() - t0) * 1000, 0


async def run_concurrency(
    base_url: str,
    concurrency: int,
    total: int,
    api_key: str | None,
    question: str,
) -> dict:
    """一档并发压测。返回指标 dict。"""
    latencies: list[float] = []
    status_codes: list[int] = []
    sem = asyncio.Semaphore(concurrency)
    start = time.perf_counter()

    async with httpx.AsyncClient() as client:
        async def one():
            async with sem:
                ok, lat, code = await hit_ask(client, base_url, question, api_key)
                latencies.append(lat)
                status_codes.append(code)

        await asyncio.gather(*(one() for _ in range(total)))

    elapsed = time.perf_counter() - start
    latencies.sort()
    n = len(latencies)
    errors = sum(1 for c in status_codes if c != 200)

    def pct(p: float) -> float:
        return latencies[min(n - 1, int(n * p))]

    return {
        "concurrency": concurrency,
        "total": total,
        "qps": round(n / elapsed, 1) if elapsed > 0 else 0,
        "p50_ms": round(pct(0.50)),
        "p95_ms": round(pct(0.95)),
        "p99_ms": round(pct(0.99)),
        "error_rate": round(errors / n * 100, 1) if n else 0,
        "elapsed_s": round(elapsed, 2),
    }


async def main_async(args) -> None:
    base_url = args.base_url.rstrip("/")
    print("=" * 78)
    print(f"压测 {base_url}/api/ask（每档 {args.requests} 请求）")
    print("=" * 78)
    print(f"\n{'并发':<6} {'QPS':<8} {'P50(ms)':<10} {'P95(ms)':<10} "
          f"{'P99(ms)':<10} {'错误率':<8} 说明")
    print("-" * 78)

    results = []
    for c in args.concurrency:
        r = await run_concurrency(
            base_url, c, args.requests, args.api_key, args.question,
        )
        results.append(r)
        if r["error_rate"] > 5:
            note = "🔴 错误率高，已达瓶颈（上游限流？）"
        elif r["p95_ms"] > 5000:
            note = "🟡 P95>5s，接近瓶颈"
        else:
            note = "🟢 正常"
        print(f"{r['concurrency']:<6} {r['qps']:<8} {r['p50_ms']:<10} "
              f"{r['p95_ms']:<10} {r['p99_ms']:<10} {r['error_rate']}%{'':<3} {note}")

    # 写报告
    report_path = _ROOT / "loadtest" / "REPORT.md"
    _write_report(report_path, base_url, results)
    print(f"\n📄 报告已写入 {report_path}")


def _write_report(path: Path, base_url: str, results: list[dict]) -> None:
    lines = [
        "# 压测报告（LLMOps L11）\n",
        f"> 目标：`{base_url}/api/ask` ｜ 生成时间：{time.strftime('%Y-%m-%d %H:%M')}\n",
        "\n## 结果\n",
        "| 并发 | QPS | P50(ms) | P95(ms) | P99(ms) | 错误率 |",
        "|------|-----|---------|---------|---------|--------|",
    ]
    for r in results:
        lines.append(
            f"| {r['concurrency']} | {r['qps']} | {r['p50_ms']} | "
            f"{r['p95_ms']} | {r['p99_ms']} | {r['error_rate']}% |"
        )
    lines += [
        "\n## 解读\n",
        "- **QPS 随并发线性增长到某点后停滞** → 那点就是吞吐天花板",
        "- **P95 在某并发档突然飙升** → 容量饱和，排队严重",
        "- **错误率上升（通常 429）** → 上游 API 限流，是 LLM 服务的主要瓶颈",
        "- **应对**：用 Semaphore 把生产并发卡在拐点以内，保护上游不被全面封禁",
        "\n> 注：LLM 服务瓶颈通常在智谱 API 限流而非本地 CPU。",
        "> 本机未实测真实数据，本表为压测脚本产出格式（跑一次真实压测填入）。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="kb-qa 压测器")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 3, 5],
                        help="并发档位列表")
    parser.add_argument("--requests", type=int, default=20, help="每档请求数")
    parser.add_argument("--api-key", default=None, help="API key（L04 鉴权）")
    parser.add_argument("--question", default="云帆科技试用期多久", help="压测用的问题")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
