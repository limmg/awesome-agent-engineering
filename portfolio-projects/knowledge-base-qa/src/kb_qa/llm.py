"""LLM 工厂：按用途返回 ChatZhipuAI 实例。

多模型路由（复用研究助手的成本策略）：
    answer_model  glm-4        回答生成，质量关键
    rewrite_model glm-4-flash  查询改写，量大且免费
"""
from __future__ import annotations

from langchain_community.chat_models import ChatZhipuAI

from .config import settings


def get_chat_model(model: str | None = None, *, streaming: bool = False) -> ChatZhipuAI:
    if not settings.zhipuai_api_key:
        raise RuntimeError("未配置 ZHIPUAI_API_KEY（.env 或环境变量）")
    return ChatZhipuAI(
        model=model or settings.answer_model,
        api_key=settings.zhipuai_api_key,
        temperature=settings.llm_temperature,
        streaming=streaming,
    )
