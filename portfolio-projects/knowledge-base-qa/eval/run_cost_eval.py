"""成本/质量对比：glm-4 vs glm-4-flash 选型报告（LLMOps L12）。

复用 run_eval.py 的 build_samples + ragas 四指标，按两个生成模型各跑一遍，
算成本，产出对比报告 + 选型结论。把「选哪个模型」从拍脑袋变成数据决策。

用法（项目根下）：
    python eval/run_cost_eval.py                  # 全量（20 题 × 2 模型）
    python eval/run_cost_eval.py --limit 5        # 快速冒烟
    python eval/run_cost_eval.py --models glm-4 glm-4-flash  # 指定对比模型

依赖：ragas（已装）+ 智谱 API key。会真实调 LLM（每题每模型 检索+生成+judge）。
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

# 必须在 import ragas 之前注入 stub（run_eval 同款）
from kb_qa.ragas_compat import install_vertexai_stub  # noqa: E402
install_vertexai_stub()

from ragas import EvaluationDataset, RunConfig, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_relevancy, context_precision, context_recall, faithfulness,
)

from kb_qa.config import settings  # noqa: E402
from kb_qa.generate import stream_answer  # noqa: E402
from kb_qa.ingest import get_embeddings  # noqa: E402
from kb_qa.llm import get_chat_model  # noqa: E402
from kb_qa.retriever import KBRetriever  # noqa: E402
from kb_qa.tracing import compute_cost  # noqa: E402

GOLDEN_PATH = _ROOT / "eval" / "golden_set.json"
REPORT_PATH = _ROOT / "eval" / "cost_report.md"
METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]
_PRICE = {"glm-4": {"input": 50.0, "output": 50.0}, "glm-4-flash": {"input": 0.0, "output": 0.0}}
_CONCURRENCY = 4


async def _answer(question: str, docs, model: str) -> tuple[str, dict]:
    """用指定模型生成答案，返回 (答案, token 估算)。"""
    # stream_answer 内部读 settings.answer_model，这里临时改它
    original = settings.answer_model
    settings.answer_model = model
    try:
        parts = [tok async for tok in stream_answer(question, docs)]
    finally:
        settings.answer_model = original
    answer = "".join(parts)
    # token 估算（教学近似；生产用 tokenizer 精确计）
    in_tok = sum(len(d.page_content) for d in docs) // 2 + len(question) // 2
    out_tok = len(answer) // 2
    return answer, {"input": in_tok, "output": out_tok}


async def build_samples(golden, mode, model, kb) -> tuple[list[dict], float]:
    """对 golden set 每题用指定模型生成，产出 ragas 样本 + 累计成本。"""
    sem = asyncio.Semaphore(_CONCURRENCY)
    total_cost = 0.0

    async def one(item):
        nonlocal total_cost
        async with sem:
            docs = await asyncio.to_thread(kb.retrieve, item["question"], mode)
            answer, usage = await _answer(item["question"], docs, model)
            total_cost += compute_cost(model, usage)
        return {
            "user_input": item["question"],
            "retrieved_contexts": [d.page_content for d in docs],
            "response": answer,
            "reference": item["ground_truth"],
        }

    samples = list(await asyncio.gather(*(one(it) for it in golden)))
    return samples, total_cost


def run_model(golden, mode, model, kb) -> dict:
    """一个模型的完整评估：生成样本 → ragas 四指标 → 汇总 + 成本。"""
    t0 = time.time()
    print(f"\n▶ model={model}：生成 {len(golden)} 题答案…")
    samples, cost = asyncio.run(build_samples(golden, mode, model, kb))

    print(f"▶ model={model}：ragas 四指标评估中…")
    result = evaluate(
        dataset=EvaluationDataset.from_list(samples),
        metrics=METRICS,
        llm=LangchainLLMWrapper(get_chat_model(settings.rewrite_model)),  # judge 用 flash 省 token
        embeddings=LangchainEmbeddingsWrapper(get_embeddings()),
        run_config=RunConfig(max_workers=_CONCURRENCY, timeout=120),
        show_progress=True,
    )
    rows = result.scores if isinstance(result.scores, list) else result.scores.to_list()

    import math
    def _valid(vals):
        return [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]

    aggregate = {}
    for m in METRICS:
        vals = _valid([r.get(m.name) for r in rows])
        aggregate[m.name] = round(sum(vals) / len(vals), 4) if vals else None
    print(f"✅ model={model} 完成（{time.time()-t0:.0f}s）：{aggregate} 成本=¥{cost:.4f}")
    return {"model": model, "aggregate": aggregate, "cost": round(cost, 4),
            "n_questions": len(golden)}


def write_report(path, results, golden_n) -> None:
    lines = [
        "# 成本/质量选型报告（LLMOps L12）\n",
        f"> 同一 golden set（{golden_n} 题）下生成模型对比 ｜ "
        f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}\n",
        "\n## 质量对比\n",
        "| 模型 | faithfulness | answer_relevancy | context_precision | context_recall |",
        "|------|-------------|------------------|-------------------|----------------|",
    ]
    for r in results:
        a = r["aggregate"]
        lines.append(
            f"| {r['model']} | {a.get('faithfulness')} | {a.get('answer_relevancy')} | "
            f"{a.get('context_precision')} | {a.get('context_recall')} |"
        )
    lines += [
        "\n## 成本对比\n",
        "| 模型 | 总成本 | 单题成本 |",
        "|------|--------|----------|",
    ]
    for r in results:
        per = r["cost"] / golden_n if golden_n else 0
        lines.append(f"| {r['model']} | ¥{r['cost']:.4f} | ¥{per:.5f} |")

    # 决策
    lines += ["\n## 选型结论\n"]
    if len(results) >= 2:
        g4 = next((r for r in results if r["model"] == "glm-4"), None)
        fl = next((r for r in results if r["model"] == "glm-4-flash"), None)
        if g4 and fl:
            faith_gap = (g4["aggregate"].get("faithfulness") or 0) - (fl["aggregate"].get("faithfulness") or 0)
            if faith_gap > 0.15:
                lines += [
                    f"- **生成环节 → glm-4**：faithfulness 高 {faith_gap:.2f}，"
                    f"flash 明显更爱撒谎，核心质量不能省",
                    f"- **改写/judge → glm-4-flash**：质量要求低 + 免费，辅助环节最优",
                    f"\n> 成本：全程 glm-4 约 ¥{g4['cost']:.2f}/{golden_n}题；"
                    f"混合（生成 glm-4 + 辅助 flash）可省辅助环节费用。",
                ]
            else:
                lines.append(f"- faithfulness 差仅 {faith_gap:.2f}，flash 够用 → 可考虑全程 flash 省钱")
    lines.append(
        "\n> context 指标是对照组（取决于检索，与生成模型无关），两模型应基本相同；"
        "若差异大需检查实验。\n"
        "\n> 注：本机未实测真实数据时，本表为脚本产出格式（跑一次会自动覆写）。"
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="glm-4 vs flash 成本/质量对比")
    parser.add_argument("--models", nargs="+", default=["glm-4", "glm-4-flash"])
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（冒烟）")
    args = parser.parse_args()

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if args.limit:
        golden = golden[: args.limit]
    mode = "rerank" if settings.enable_rerank else "hybrid"
    print(f"golden set：{len(golden)} 题；对比模型：{args.models}；检索模式：{mode}")

    kb = KBRetriever()  # 复用，避免重复建 BM25 索引
    results = [run_model(golden, mode, m, kb) for m in args.models]

    write_report(REPORT_PATH, results, len(golden))
    print(f"\n📄 报告已写入 {REPORT_PATH}")

    # 对比表
    print(f"\n{'指标':<22}" + "".join(f"{m:>14}" for m in args.models))
    for m in METRICS:
        print(f"{m.name:<22}" + "".join(
            f"{r['aggregate'].get(m.name):>14}" for r in results))
    print(f"{'成本(¥)':<22}" + "".join(f"{r['cost']:>14}" for r in results))


if __name__ == "__main__":
    main()
