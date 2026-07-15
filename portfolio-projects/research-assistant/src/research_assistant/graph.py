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
from .config import settings


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

    拓扑（Frontier L05：双通道路由）：
        START → research_team → writer → reviewer ─(条件)─→ END
                                                    │
                                          ┌─────────┼──────────┐
                                          ▼         ▼          ▼
                                       rework  re_research    pass
                                          │         │          │
                                       writer   research_team  END
                                       (重写)    (定向补研)

    review_route 返回：
        - END：通过
        - "writer"：文字不合格 → 重写（rewrite_count++）
        - "research_team"：事实冲突 → 定向补研（re_research_count++）

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

    # AgentOps L04：enable_publish 时加 publish 节点（reviewer PASS 后发布）
    # 关闭时图结构与现状完全一致（review_route 的 pass→END）。
    if settings.enable_publish:
        from .publish import make_publish_node
        builder.add_node("publish", make_publish_node())
        # review_route 的 pass → publish → END（而非直接 END）
        # 用 conditional_edge 的 path_map 把 pass 映射到 publish
        def review_route_with_publish(state):
            target = review_route(state)
            # review_route 返回 END 表示 pass → 改路由到 publish
            return "publish" if target == END else target
        builder.add_conditional_edges("reviewer", review_route_with_publish)
        builder.add_edge("publish", END)
    else:
        # ⭐ 双通道条件边：pass→END, rework→writer, re_research→research_team
        builder.add_conditional_edges("reviewer", review_route)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
