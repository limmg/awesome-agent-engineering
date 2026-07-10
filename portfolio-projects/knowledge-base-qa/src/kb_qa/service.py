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
from .retriever import KBRetriever

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

    # 追问改写：有历史时把问题补全成独立问题再检索
    search_query = question
    if past:
        yield _event("progress", {"stage": "condense", "detail": "改写追问为独立问题"})
        t0 = time.perf_counter()
        search_query = await condense_question(question, past)
        log_event(
            _log, "condense.done",
            duration_ms=round((time.perf_counter() - t0) * 1000),
            rewritten=search_query[:80],
        )

    yield _event("progress", {"stage": "retrieve", "detail": f"混合检索中（mode={mode or 'default'}）"})
    t0 = time.perf_counter()
    kb = await get_kb()
    docs = await asyncio.to_thread(kb.retrieve, search_query, mode)
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
    answer_parts: list[str] = []
    async for token in stream_answer(question, docs, past):
        answer_parts.append(token)
        yield _event("token", {"content": token})

    answer = "".join(answer_parts)
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
