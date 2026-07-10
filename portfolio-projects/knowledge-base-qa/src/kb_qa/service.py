"""服务编排：把 检索 → 生成 → 历史 串成 SSE 事件流。

事件协议（前端按 event 分发）：
    progress —— {stage, detail}   检索/改写进度
    sources  —— [{idx, source, section, preview}]  引用材料列表
    token    —— {content}         逐 token 输出
    done     —— {answer, thread_id, mode}  完整结果（落历史后发出）
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

from .config import settings
from .generate import condense_question, stream_answer
from .history import ChatHistory
from .observability import estimate_tokens, get_logger, log_event, new_trace_id, set_trace_id
from .online_eval import sample_and_evaluate
from .retriever import KBRetriever
from .tracing import start_trace, trace_generation, trace_span

# 服务级 logger：问答流程的关键事件都从这儿打（带 trace_id 贯穿）。
_log = get_logger("kb_qa.service")

_kb: KBRetriever | None = None
_kb_lock = asyncio.Lock()


async def get_kb() -> KBRetriever:
    """进程级单例：BM25 索引构建有成本，建一次答多次。"""
    global _kb
    async with _kb_lock:
        if _kb is None:
            _kb = await asyncio.to_thread(KBRetriever)
        return _kb


async def reset_kb() -> None:
    """文档上传/入库后调用：作废旧索引，下次请求重建。"""
    global _kb
    async with _kb_lock:
        _kb = None


def _event(name: str, data: dict | list) -> dict:
    return {"event": name, "data": json.dumps(data, ensure_ascii=False)}


async def stream_ask(
    question: str,
    thread_id: str,
    mode: str | None = None,
    trace_id: str | None = None,
) -> AsyncIterator[dict]:
    """一次问答的完整事件流。

    trace_id：调用方可传入（如从 HTTP 请求头/响应头统一），不传则本函数生成。
    设置进 contextvars 后，本次问答打出的所有日志都带同一个 id，
    线上可按 trace_id 还原「改写→检索→生成」整条链路（LLMOps L01）。
    """
    # 请求入口：确定 trace_id 并注入上下文（并发请求互不串台）
    tid = trace_id or new_trace_id()
    set_trace_id(tid)
    log_event(_log, "request.start", question=question, thread_id=thread_id, mode=mode)

    history = ChatHistory()
    past = history.get(thread_id)

    # 开一个 trace 贯穿整次问答（LLMOps L02）：
    #   - 配了 Langfuse → 上报面板，可视化每一步耗时/输入输出/成本
    #   - 没配 → 降级打印 trace 树到 stderr，等价可观测
    with start_trace("kb_qa.ask", question=question, thread_id=thread_id,
                     trace_id=tid, mode=mode or "default"):
        # 追问改写：有历史时把问题补全成独立问题再检索
        search_query = question
        if past:
            yield _event("progress", {"stage": "condense", "detail": "改写追问为独立问题"})
            t0 = time.perf_counter()
            with trace_generation("condense", model=settings.rewrite_model) as g:
                search_query = await condense_question(question, past)
                g.usage = {"input": estimate_tokens(question), "output": estimate_tokens(search_query), "unit": "TOKENS"}
            log_event(
                _log, "condense.done",
                duration_ms=round((time.perf_counter() - t0) * 1000),
                rewritten=search_query[:80],
            )

        yield _event("progress", {"stage": "retrieve", "detail": f"混合检索中（mode={mode or 'default'}）"})
        t0 = time.perf_counter()
        with trace_span("retrieve", query=search_query) as rspan:
            kb = await get_kb()
            docs = await asyncio.to_thread(kb.retrieve, search_query, mode)
            rspan.output = f"{len(docs)} 条材料"
            rspan.metadata["hits"] = len(docs)
        log_event(
            _log, "retrieve.done",
            hits=len(docs),
            mode=mode or ("rerank" if settings.enable_rerank else "hybrid"),
            duration_ms=round((time.perf_counter() - t0) * 1000),
        )

        yield _event(
            "sources",
            [
                {
                    "idx": i,
                    "source": d.metadata.get("source", "?"),
                    "section": d.metadata.get("section", ""),
                    "preview": d.page_content[:120],
                }
                for i, d in enumerate(docs, 1)
            ],
        )

        t0 = time.perf_counter()
        with trace_generation("answer", model=settings.answer_model) as gen:
            answer_parts: list[str] = []
            async for token in stream_answer(question, docs, past):
                answer_parts.append(token)
                yield _event("token", {"content": token})
            answer = "".join(answer_parts)
            gen.output = answer[:500]  # 截断避免 trace 过大
            gen.usage = {"input": sum(estimate_tokens(d.page_content) for d in docs) + estimate_tokens(question),
                         "output": estimate_tokens(answer), "unit": "TOKENS"}

        history.append(thread_id, "human", question)
        history.append(thread_id, "ai", answer)

        log_event(
            _log, "generate.done",
            tokens=estimate_tokens(answer),
            duration_ms=round((time.perf_counter() - t0) * 1000),
            chars=len(answer),
        )

    yield _event(
        "done",
        {
            "answer": answer,
            "thread_id": thread_id,
            "trace_id": tid,  # 回吐给前端/调用方，方便排障时拿 id 捞日志
            "mode": mode or ("rerank" if settings.enable_rerank else "hybrid"),
        },
    )
    log_event(_log, "request.done")

    # 线上评估闭环（LLMOps L03）：done 后异步抽样评估，绝不阻塞已返回的响应。
    # sample_and_evaluate 内部按 eval_sample_rate 决定是否真跑；低分入 review_queue。
    # 用 create_task 派发：用户已拿到答案，评估在后台跑，失败也只打日志不影响服务。
    asyncio.create_task(sample_and_evaluate(
        question=question,
        answer=answer,
        contexts=[d.page_content for d in docs],
        thread_id=thread_id,
        trace_id=tid,
    ))
