"""图组装：双层图（并行子图 + 父图）。

阶段 1 范围：先搭 L09 同款结构（research_team[子图] → writer），
真实搜索 researcher 已替换。审稿回路（reviewer 条件边）在阶段 2 加入。

依赖注入设计：
    所有 build_* 函数接受 LLM 实例作参数（不内部 new），便于：
        - 测试时注入 mock LLM
        - 多模型路由（smart/fast 不同实例传不同节点）
        - 配置变更不重写图逻辑
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    make_research_team,
    make_researcher,
    make_reviewer,
    make_split,
    make_summarize,
    make_writer,
    review_route,
    route_to_researchers,
)
from .state import ResearchState, SystemState


def build_research_subgraph(fast_llm, smart_llm):
    """构建并行研究子图。

    拓扑（L04 map-reduce + L06 多模型）：
        START → split ──(Send×N)──→ researcher(并行) → summarize → END
                (fast)              (fast+真实搜索)     (smart)

    Args:
        fast_llm: split/researcher 用（成本优先）
        smart_llm: summarize 用（质量优先）
    """
    builder = StateGraph(ResearchState)
    builder.add_node("split", make_split(fast_llm))
    builder.add_node("researcher", make_researcher(fast_llm))
    builder.add_node("summarize", make_summarize(smart_llm))

    builder.add_edge(START, "split")
    builder.add_conditional_edges("split", route_to_researchers)  # ⭐ 并行 fan-out
    builder.add_edge("researcher", "summarize")                   # 所有并行完成 → 汇总
    builder.add_edge("summarize", END)
    return builder.compile()


def build_system(smart_llm, fast_llm, research_subgraph, checkpointer=None):
    """构建完整研究系统（父图）。

    拓扑（阶段 2：加审稿回路）：
        START → research_team(子图作节点) → writer → reviewer ─(条件)─→ END
                                                         │              │
                                                         └── rework ────┘→ writer(回环)
    - reviewer 通过或 rewrite_count 达上限 → END
    - reviewer 不通过 → 回 writer（带 feedback，rewrite_count++）

    Args:
        smart_llm: writer + reviewer 用（质量优先）
        fast_llm: 预留（子图内 split/researcher 用，父图暂不直接用）
        research_subgraph: 已编译的并行研究子图
        checkpointer: 可选；不传则纯内存无记忆（测试用），
                      生产传 SqliteSaver 实现跨轮/跨重启记忆
    """
    builder = StateGraph(SystemState)
    builder.add_node("research_team", make_research_team(research_subgraph))
    builder.add_node("writer", make_writer(smart_llm))
    builder.add_node("reviewer", make_reviewer(smart_llm))

    builder.add_edge(START, "research_team")
    builder.add_edge("research_team", "writer")
    builder.add_edge("writer", "reviewer")
    # ⭐ 审稿条件边：review_route 返回 END（通过）或 "writer"（重写）
    builder.add_conditional_edges("reviewer", review_route)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
