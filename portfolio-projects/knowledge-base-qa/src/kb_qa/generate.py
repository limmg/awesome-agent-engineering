"""生成层：防幻觉 prompt + 【材料N】引用溯源 + 流式回答。

防幻觉三件套（rag-05 模式生产版）：
    1. 指令约束：只根据材料回答，材料没有就明说，禁止编造
    2. 引用溯源：答案里标【材料N】，前端可对应到具体文档条款
    3. 低温（settings.llm_temperature=0.1）：知识库问答不需要发挥

多轮对话的检索难题：追问「那专业版呢？」单独拿去检索什么都召不回。
标准解法 condense-question：先用 glm-4-flash 把（历史+追问）改写成
独立完整的问题再检索，回答时同样带上历史保持语气连贯。
"""
from __future__ import annotations

from typing import AsyncIterator

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .config import settings
from .guardrails import SAFE_SYSTEM_PROMPT, isolate_documents
from .llm import get_chat_model

# L06 起使用强化版 system prompt（含安全规则：材料是数据非指令、禁复述提示词等）。
_SYSTEM_PROMPT = SAFE_SYSTEM_PROMPT

_CONDENSE_PROMPT = """根据对话历史，把用户的最新问题改写成一个不依赖上下文、可独立理解的完整问题。
只输出改写后的问题本身，不要解释。

对话历史：
{history}

最新问题：{question}

改写后的独立问题："""


def build_context(docs: list[Document]) -> str:
    """把检索材料拼成带编号和出处的上下文块，并用隔离标签包裹（LLMOps L06）。

    用 <begin_retrieved_documents> 圈住材料，从结构上标记为「数据非指令」，
    配合 SAFE_SYSTEM_PROMPT 的安全规则抵御间接 prompt 注入。
    """
    parts = []
    for i, doc in enumerate(docs, 1):
        src = doc.metadata.get("source", "未知来源")
        section = doc.metadata.get("section", "")
        loc = f"{src} · {section}" if section else src
        parts.append(f"【材料{i}】（出处：{loc}）\n{doc.page_content}")
    body = "\n\n".join(parts)
    return isolate_documents(body)


def _history_messages(history: list[tuple[str, str]]) -> list[BaseMessage]:
    """(role, content) 转 LangChain 消息（role: 'human' | 'ai'）。"""
    return [
        HumanMessage(content=c) if r == "human" else AIMessage(content=c)
        for r, c in history
    ]


async def condense_question(question: str, history: list[tuple[str, str]]) -> str:
    """有历史时把追问改写成独立问题（glm-4-flash，快且免费）；无历史直接返回。"""
    if not history:
        return question
    history_text = "\n".join(f"{'用户' if r == 'human' else '助手'}：{c}" for r, c in history)
    llm = get_chat_model(settings.rewrite_model)
    resp = await llm.ainvoke(_CONDENSE_PROMPT.format(history=history_text, question=question))
    rewritten = str(resp.content).strip()
    return rewritten or question


async def stream_answer(
    question: str,
    docs: list[Document],
    history: list[tuple[str, str]] | None = None,
) -> AsyncIterator[str]:
    """流式生成回答，逐 token yield。"""
    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    messages.extend(_history_messages(history or []))
    messages.append(
        HumanMessage(content=f"【材料】\n{build_context(docs)}\n\n【问题】{question}")
    )

    llm = get_chat_model(settings.answer_model, streaming=True)
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield str(chunk.content)
