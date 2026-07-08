"""LLM 工厂：集中创建多模型实例（多模型路由，L06/L09 成本优化）。

设计：
    - smart_llm（glm-4）：决策/写作类，贵但聪明。用在 summarize / writer / reviewer。
    - fast_llm（glm-4-flash）：执行类，免费快。用在 split / researcher（并行量大）。
    - 工厂函数集中创建，避免散落 new；测试时可注入 mock。

成本账（L06 思路）：3 个并行 researcher 用免费模型 + 1 个 writer 用付费模型，
对比全部用付费模型，约省 80% 调用成本。
"""
from __future__ import annotations

import warnings

# 抑制两类已知噪声（课程里验证过的无害告警）：
# 1) langchain-community sunset 提示
# 2) jwt InsecureKeyLengthWarning（langchain 链路间接依赖触发）
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")
try:
    from jwt.warnings import InsecureKeyLengthWarning
    warnings.filterwarnings("ignore", category=InsecureKeyLengthWarning)
except ImportError:
    pass

from langchain_community.chat_models import ChatZhipuAI

from .config import settings


def make_smart_llm() -> ChatZhipuAI:
    """决策/写作模型实例（质量优先）。"""
    return ChatZhipuAI(
        model=settings.smart_model,
        api_key=settings.zhipuai_api_key,
        temperature=settings.llm_temperature,
    )


def make_fast_llm() -> ChatZhipuAI:
    """执行模型实例（成本/速度优先，用于并行）。"""
    return ChatZhipuAI(
        model=settings.fast_model,
        api_key=settings.zhipuai_api_key,
        temperature=settings.llm_temperature,
    )
