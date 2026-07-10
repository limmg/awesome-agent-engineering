"""ragas 评估 runner：golden set → 跑 RAG → 四指标 → 结果落盘。

用法（项目根下）：
    python eval/run_eval.py --modes hybrid rerank            # 消融对比
    python eval/run_eval.py --modes rerank --limit 5         # 快速冒烟

四指标含义（诊断哪个环节拖后腿）：
    context_recall     检索层：该召回的材料召回了吗（低 → 召回不足，调混合权重/改写）
    context_precision  检索层：召回的材料排序质量（低 → 重排没起作用）
    faithfulness       生成层：答案是否忠于材料（低 → 防幻觉 prompt 失效）
    answer_relevancy   生成层：答案是否切题（低 → prompt 跑偏/材料噪声大）
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

# 必须在 import ragas 之前注入 stub（见 ragas_compat 文档）
from kb_qa.ragas_compat import install_vertexai_stub  # noqa: E402

install_vertexai_stub()

from ragas import EvaluationDataset, RunConfig, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from kb_qa.generate import stream_answer  # noqa: E402
from kb_qa.ingest import get_embeddings  # noqa: E402
from kb_qa.llm import get_chat_model  # noqa: E402
from kb_qa.retriever import KBRetriever  # noqa: E402

GOLDEN_PATH = _ROOT / "eval" / "golden_set.json"
METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]
_CONCURRENCY = 4  # 答案生成并发（智谱 QPS 限制内）


async def _answer(question: str, docs) -> str:
    parts = [tok async for tok in stream_answer(question, docs)]
    return "".join(parts)


async def build_samples(golden: list[dict], mode: str) -> list[dict]:
    """对 golden set 每题跑「检索+生成」，产出 ragas 样本。"""
    kb = KBRetriever()
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(item: dict) -> dict:
        async with sem:
            docs = await asyncio.to_thread(kb.retrieve, item["question"], mode)
            answer = await _answer(item["question"], docs)
        return {
            "user_input": item["question"],
            "retrieved_contexts": [d.page_content for d in docs],
            "response": answer,
            "reference": item["ground_truth"],
        }

    return list(await asyncio.gather(*(one(item) for item in golden)))


def run_mode(golden: list[dict], mode: str) -> dict:
    """一个检索模式的完整评估：生成样本 → ragas 四指标 → 汇总。"""
    t0 = time.time()
    print(f"\n▶ mode={mode}：生成 {len(golden)} 题的检索+回答…")
    samples = asyncio.run(build_samples(golden, mode))

    print(f"▶ mode={mode}：ragas 四指标评估中（judge={get_chat_model().model_name}）…")
    result = evaluate(
        dataset=EvaluationDataset.from_list(samples),
        metrics=METRICS,
        llm=LangchainLLMWrapper(get_chat_model()),
        embeddings=LangchainEmbeddingsWrapper(get_embeddings()),
        run_config=RunConfig(max_workers=_CONCURRENCY, timeout=120),
        show_progress=True,
    )

    rows = result.scores if isinstance(result.scores, list) else result.scores.to_list()

    def _valid(values: list) -> list[float]:
        """judge 调用超时会产生 None/NaN，聚合时剔除（样本数会在报告里注明）。"""
        import math
        return [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]

    aggregate = {}
    for m in METRICS:
        vals = _valid([r.get(m.name) for r in rows])
        aggregate[m.name] = round(sum(vals) / len(vals), 4) if vals else None
    print(f"✅ mode={mode} 完成（{time.time() - t0:.0f}s）：{aggregate}")
    return {
        "mode": mode,
        "aggregate": aggregate,
        "per_question": [
            {"question": s["user_input"], **{m.name: r.get(m.name) for m in METRICS}}
            for s, r in zip(samples, rows)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ragas 四指标评估")
    parser.add_argument("--modes", nargs="+", default=["hybrid", "rerank"],
                        choices=["vector", "hybrid", "rerank"])
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（冒烟用）")
    parser.add_argument("--out", default=str(_ROOT / "eval" / "results.json"))
    args = parser.parse_args()

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if args.limit:
        golden = golden[: args.limit]
    print(f"golden set：{len(golden)} 题；模式：{args.modes}")

    results = [run_mode(golden, mode) for mode in args.modes]

    Path(args.out).write_text(
        json.dumps({"n_questions": len(golden), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n📄 结果已写入 {args.out}")

    # 对比表
    print(f"\n{'指标':<20}" + "".join(f"{m:>10}" for m in args.modes))
    for m in METRICS:
        print(f"{m.name:<20}" + "".join(f"{r['aggregate'][m.name]:>10.4f}" for r in results))


if __name__ == "__main__":
    main()
