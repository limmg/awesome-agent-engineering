"""线上评估闭环：抽样 + 复用 ragas judge + 坏答案队列（LLMOps L03）。

把离线的 ragas 评估（eval/run_eval.py）延伸到线上：
    真实问答 ──抽样──▶ 跑 faithfulness+answer_relevancy（无需 ground_truth）
                          └─▶ 低分进 review_queue.jsonl
    用户点踩 ──────────────────────────────────▶ 100% 入队（强信号不抽样）

设计要点：
    - 复用现有 ragas 管线（install_vertexai_stub + evaluate），
      不重复造 judge；只跑不需要 ground_truth 的两个指标
    - evaluate_sample 是 async，由 service.py 用 create_task 异步派发，绝不阻塞响应
    - 入队写 jsonl（追加写、崩了不丢历史、可 grep）
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from pathlib import Path

from .config import settings
from .observability import get_logger, log_event

_log = get_logger("kb_qa.online_eval")

# ragas 是重依赖，延迟到首次评估才 import（不影响服务启动速度）
_ragas_ready = False
_faithfulness = None
_answer_relevancy = None


def _ensure_ragas() -> bool:
    """延迟初始化 ragas（注入 vertexai stub + 取指标）。

    返回 True 表示 ragas 可用；失败返回 False（调用方降级：跳过评估）。
    幂等：只初始化一次。
    """
    global _ragas_ready, _faithfulness, _answer_relevancy
    if _ragas_ready:
        return True
    try:
        # 必须在 import ragas 之前注入 stub（见 ragas_compat 文档）
        from .ragas_compat import install_vertexai_stub
        install_vertexai_stub()
        from ragas.metrics import answer_relevancy, faithfulness  # noqa
        _faithfulness = faithfulness
        _answer_relevancy = answer_relevancy
        _ragas_ready = True
        return True
    except Exception as e:  # ragas 未装 / 版本不兼容
        log_event(_log, "ragas.unavailable", level=30, error=str(e))  # WARNING
        return False


# ── 抽样 ─────────────────────────────────────────────────────────
def should_sample(rate: float | None = None, rng: random.Random | None = None) -> bool:
    """按采样率随机决定是否评估本条问答。

    rate 默认读 settings.eval_sample_rate。
    概率抽样（非固定间隔）保证任意时间段都有样本，对连续流量更鲁棒。
    """
    r = rate if rate is not None else settings.eval_sample_rate
    if r >= 1.0:
        return True
    if r <= 0.0:
        return False
    return (rng or random).random() < r


# ── judge：复用 ragas 跑两个无需 ground_truth 的指标 ─────────────
async def evaluate_sample(
    question: str,
    answer: str,
    contexts: list[str],
) -> dict[str, float] | None:
    """对单条问答跑 faithfulness + answer_relevancy。

    这两个指标只需要 (question, answer, contexts)，不需要 ground_truth——
    正好覆盖线上「没有标准答案」的场景，且聚焦最易出问题的生成层。

    返回 {faithfulness, answer_relevancy}；ragas 不可用或出错返回 None。
    """
    if not _ensure_ragas():
        return None
    try:
        # 延迟 import（_ensure_ragas 已保证 stub 注入）
        from ragas import EvaluationDataset, RunConfig, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper

        from .ingest import get_embeddings
        from .llm import get_chat_model

        sample = [{
            "user_input": question,
            "retrieved_contexts": contexts,
            "response": answer,
        }]
        result = evaluate(
            dataset=EvaluationDataset.from_list(sample),
            metrics=[_faithfulness, _answer_relevancy],
            llm=LangchainLLMWrapper(get_chat_model()),
            embeddings=LangchainEmbeddingsWrapper(get_embeddings()),
            run_config=RunConfig(max_workers=2, timeout=60),
            raise_exceptions=False,
            show_progress=False,
        )
        rows = result.scores if isinstance(result.scores, list) else result.scores.to_list()
        if not rows:
            return None
        r = rows[0]
        return {
            "faithfulness": _safe_float(r.get("faithfulness")),
            "answer_relevancy": _safe_float(r.get("answer_relevancy")),
        }
    except Exception as e:
        log_event(_log, "evaluate.failed", level=40, error=str(e), question=question[:60])
        return None


def _safe_float(v) -> float | None:
    """ragas 偶尔返回 None/NaN（judge 超时），统一转 None。"""
    import math
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), 4)


# ── 阈值过滤 ─────────────────────────────────────────────────────
def is_low_quality(scores: dict[str, float | None], threshold: float | None = None) -> bool:
    """任一指标低于阈值即判低分（用 min 而非 avg：宁可多看，不漏崩盘维度）。

    None 视为低分（judge 没出分 = 异常，值得人工看一眼）。
    """
    th = threshold if threshold is not None else settings.eval_score_threshold
    vals = [v for v in scores.values() if v is not None]
    if len(vals) < len(scores):  # 有 None → 判低分
        return True
    return min(vals) < th


# ── 入队 ─────────────────────────────────────────────────────────
def enqueue_review(
    question: str,
    answer: str,
    contexts: list[str],
    scores: dict | None,
    source: str,
    thread_id: str | None = None,
    rating: str | None = None,
) -> None:
    """把一条坏样本追加到 review_queue.jsonl。

    source: "sample"（抽样）/ "feedback"（点踩）。
    写 jsonl：追加写 O(1)、崩了不丢历史、可 grep/jq。
    """
    queue_path = Path(settings.eval_review_queue_path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "question": question,
        "answer": answer,
        "contexts": [c[:200] for c in contexts],  # 截断避免队列膨胀
        "scores": scores,
        "source": source,
        "thread_id": thread_id,
        "rating": rating,
        "ts": int(time.time()),
    }
    with queue_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log_event(_log, "review.enqueued", source=source, question=question[:40])


# ── 主入口：异步评估一条问答（供 service.py create_task 调用）────
async def sample_and_evaluate(
    question: str,
    answer: str,
    contexts: list[str],
    thread_id: str | None = None,
    trace_id: str | None = None,
) -> None:
    """抽样 → judge → 阈值过滤 → 入队。完整闭环，异步执行不阻塞响应。

    被 service.py 在问答 done 后用 asyncio.create_task 派发。
    任何环节失败都静默（只打日志），绝不影响用户已收到的答案。
    """
    set_trace = None
    try:
        # 把 trace_id 注入日志上下文，便于把评估记录和原问答串起来
        from .observability import set_trace_id
        if trace_id:
            set_trace_id(trace_id)
    except Exception:
        pass

    if not should_sample():
        return  # 未抽中：静默跳过（绝大多数请求走这条）

    log_event(_log, "sample.hit", question=question[:40], thread_id=thread_id)
    scores = await evaluate_sample(question, answer, contexts)
    if scores is None:
        return  # judge 不可用/失败：静默（已打日志）

    if is_low_quality(scores):
        enqueue_review(question, answer, contexts, scores, source="sample", thread_id=thread_id)
        log_event(_log, "low_quality.detected", scores=scores, question=question[:40])
    else:
        log_event(_log, "sample.passed", scores=scores)


def enqueue_feedback(
    question: str,
    answer: str,
    contexts: list[str],
    rating: str,
    thread_id: str | None = None,
) -> None:
    """处理用户反馈：点踩（down）100% 入队，不抽样不判分。

    点赞（up）不入队——那是好样本，不需要优化。点踩是强信号，永不漏。
    """
    if rating != "down":
        return
    enqueue_review(question, answer, contexts, scores=None, source="feedback",
                   thread_id=thread_id, rating=rating)
