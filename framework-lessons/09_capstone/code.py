"""
Lesson 09 — 毕业项目：LangGraph 研究助手
=========================================
综合 L06-L08 全部技术，把 Agent L09 手写的研究助手重做成多节点图。

图结构：
    START → research →(条件)→ tools → research（回路，搜索循环）
                   →(搜够了)→ report → END

集成技术：
    - StateGraph + 节点 + 条件边（L06）
    - @tool + ToolNode（L07）
    - 自定义 State（携带 topic + report）
    - Checkpointer 跨轮记忆（L08）
    - Mermaid 可视化

映射：agent-lessons/09_capstone（手写 run_research_agent）

运行：python framework-lessons/09_capstone/code.py
"""
# 消除 langchain-community / duckduckgo 的警告
# duckduckgo_search 改名为 ddgs，每次调用都会刷 RuntimeWarning，全局忽略
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*renamed.*")

import os
from typing import Annotated, TypedDict

from dotenv import load_dotenv

try:  # 兼容旧 Python 的 sqlite3（3.9+ 可忽略）
    import pysqlite3
    import sys
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

# === LangChain + LangGraph 组件 ===
from langchain_community.chat_models import ChatZhipuAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages   # messages 自动追加的 reducer
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from duckduckgo_search import DDGS

CHAT_MODEL = "glm-4"          # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 第 1 步：自定义 State（对比 L06 的 MessagesState）
# ════════════════════════════════════════════════════════════
# Agent L09 手写时用 messages + collected_sources 两个变量分别维护
# 这里用自定义 State 把它们统一起来，图能自动管理
class ResearchState(TypedDict):
    """研究助手的状态。

    messages: 对话历史（用 add_messages reducer 自动追加，不覆盖）
    topic:    研究主题（report 节点需要它来生成报告）
    report:   最终报告（report 节点产出）
    """
    messages: Annotated[list, add_messages]
    topic: str
    report: str


# ════════════════════════════════════════════════════════════
# 第 2 步：定义工具（@tool，对比 Agent L09 手写的 TOOLS_SPEC）
# ════════════════════════════════════════════════════════════
@tool
def web_search(query: str) -> str:
    """联网搜索互联网信息。需要查找某个主题的资料、最新信息、事实数据时使用。

    如果一次搜索信息不够，可以换不同关键词多次搜索。

    Args:
        query: 搜索关键词，如 'RAG技术 原理'
    """
    # Agent L09 的 web_search 函数原样复用（含错误兜底）
    try:
        results = list(DDGS().text(query, max_results=4))
        if not results:
            return f"搜索 '{query}' 没有返回结果。可以换个关键词试试。"
        formatted = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            body = r.get("body", "")[:120]
            href = r.get("href", "")
            formatted.append(f"[{i}] {title}\n    {body}\n    来源: {href}")
        return "\n".join(formatted)
    except Exception as e:
        # 错误兜底：返回友好信息，Agent 可换关键词重试（不崩溃）
        return f"搜索失败（{type(e).__name__}）。可以换个关键词或稍后再试。"


TOOLS = [web_search]


# ════════════════════════════════════════════════════════════
# 第 3 步：定义节点函数
# ════════════════════════════════════════════════════════════
# 研究 system prompt（对应 Agent L09 的 RESEARCH_SYSTEM_PROMPT）
RESEARCH_SYS = SystemMessage(content=(
    "你是一个专业的研究助手。针对用户给的研究主题，通过 web_search 联网搜索收集信息。"
    "搜索 2-3 次收集到足够信息后，直接给出总结回答（不要再调用工具）。"
    "搜索关键词要具体有针对性，同一个关键词不要重复搜。"
))


def make_research_node(llm_with_tools):
    """创建 research 节点：调模型，决定继续搜索还是给出答案。

    对比 Agent L09：循环里的 client.chat.completions.create(...)
    关键区别：Agent L09 用字符串 "FINAL_REPORT" 检测阶段切换；
    这里用条件边——模型不调工具了（无 tool_calls）就自动去 report 节点。
    """
    def research(state: ResearchState):
        # 把 system + 所有历史 messages 喂给模型
        messages = [RESEARCH_SYS] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}
    return research


def make_report_node(llm):
    """创建 report 节点：把搜集的信息整理成结构化报告。

    对比 Agent L09：循环外的 generate_report(topic, collected_info)
    现在它是一个独立的图节点——结构清晰，未来可加"审查报告"节点。
    """
    def generate_report(state: ResearchState):
        # 从 messages 里提取所有 ToolMessage（搜索结果）作为素材
        from langchain_core.messages import ToolMessage
        tool_results = [m for m in state["messages"] if isinstance(m, ToolMessage)]
        collected = "\n\n".join(f"搜索结果：\n{m.content}" for m in tool_results)
        if not collected:
            collected = "（没有搜集到搜索结果）"

        topic = state.get("topic", "未知主题")
        prompt = (
            f"你是一个研究助理。根据搜集到的信息，写一份关于「{topic}」的结构化研究报告。\n"
            f"要求：包含概述、核心要点（3-5条）、总结。标注来源。语言简洁专业。\n\n"
            f"搜集到的信息：\n{collected}"
        )
        report = llm.invoke([HumanMessage(content=prompt)]).content
        return {"report": report}
    return generate_report


# ════════════════════════════════════════════════════════════
# 第 4 步：组装图（本课核心）
# ════════════════════════════════════════════════════════════
def build_research_graph(llm):
    """组装研究助手的多节点图。

    对比 Agent L09 的单层 for 循环：这里是三个节点 + 条件边 + 回路。
    每个节点的职责单一，流程可视化、可扩展。
    """
    llm_with_tools = llm.bind_tools(TOOLS)

    builder = StateGraph(ResearchState)

    # 节点
    builder.add_node("research", make_research_node(llm_with_tools))
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_node("report", make_report_node(llm))

    # 边
    builder.add_edge(START, "research")
    # 条件边：模型要搜索去 tools，不搜索（给出答案了）去 report
    builder.add_conditional_edges(
        "research",
        tools_condition,            # 有 tool_calls → "tools"；无 → END
        {"tools": "tools", END: "report"},  # ⭐ 把 END 重定向到 report 节点
    )
    builder.add_edge("tools", "research")   # 回路：搜索完回到 research
    builder.add_edge("report", END)         # 报告生成完结束

    # 用 InMemorySaver 编译（L08 的记忆能力，让助手跨轮记住对话）
    graph = builder.compile(checkpointer=InMemorySaver())
    return graph


# ════════════════════════════════════════════════════════════
# 部分①：打印图结构（Mermaid 可视化）
# ════════════════════════════════════════════════════════════
def part_1_graph_viz(graph):
    print("\n" + "═" * 64)
    print("部分①：研究助手的图结构（对比 Agent L09 读代码才知道流程）")
    print("═" * 64)

    mermaid = graph.get_graph().draw_mermaid()
    print("\nMermaid 图（可粘贴到 mermaid.live 可视化）：")
    print(mermaid)

    print("""
┌──────────────────────────────────────────────────┐
│  Agent L09 手写的 while 循环 = 这张图             │
│                                                  │
│            ┌─────────────────────┐               │
│            │                     ▼               │
│  START──▶ research ──有tool_calls──▶ tools       │
│            │  (调模型)              (执行搜索)     │
│            │ 没tool_calls                  │      │
│            ▼                               │      │
│          report ◀────回路(回到research)───┘      │
│            │                                     │
│            ▼                                     │
│           END                                    │
│                                                  │
│  • research 节点 = 循环里的调模型 + 决策           │
│  • tools 节点   = execute_function（ToolNode 写） │
│  • report 节点  = 循环外的 generate_report        │
│  • 条件边       = 替代 "FINAL_REPORT" 字符串检测  │
│  • tools→research 回路 = for 循环                 │
└──────────────────────────────────────────────────┘
""")


# ════════════════════════════════════════════════════════════
# 部分②：研究助手跑一个真实主题（自主多轮搜索 + 报告）
# ════════════════════════════════════════════════════════════
def part_2_research(graph, thread_id="demo-1"):
    """给研究助手一个主题，看它自主搜索并生成报告。"""
    print("\n" + "═" * 64)
    print("部分②：研究助手自主搜索 + 生成报告")
    print("═" * 64)

    topic = "RAG 检索增强生成技术的核心原理"
    print(f"\n🎯 研究主题：{topic}")
    print("（助手会自主决定搜什么、搜几次，然后生成报告）\n")

    # 用 thread_id 让 Checkpointer 记住这次对话（L08 的记忆）
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 20}

    result = graph.invoke(
        {"topic": topic, "messages": [HumanMessage(content=f"请帮我研究：{topic}")], "report": ""},
        config=config,
    )

    # 打印搜索过程的轨迹
    from langchain_core.messages import ToolMessage
    print("📋 搜索过程：")
    search_count = 0
    for m in result["messages"]:
        if isinstance(m, ToolMessage):
            search_count += 1
            preview = m.content.replace("\n", " ")[:60]
            print(f"  第{search_count}次搜索结果：{preview}...")

    print(f"\n{'━' * 64}")
    print(f"📝 研究报告（共搜索 {search_count} 次）：")
    print(f"{'━' * 64}")
    print(result.get("report", "（未生成报告）"))

    return result


# ════════════════════════════════════════════════════════════
# 部分③：Checkpointer 记忆演示（跨轮追问）
# ════════════════════════════════════════════════════════════
def part_3_memory(graph, thread_id="demo-1"):
    """用同一个 thread_id 追问，演示 Checkpointer 记住了上文（L08）。"""
    print("\n\n" + "═" * 64)
    print("部分③：Checkpointer 记忆演示（用同一个 thread_id 追问）")
    print("═" * 64)

    followup = "刚才研究的这个技术，有什么主要缺点？"
    print(f"\n💬 追问：{followup}")
    print("（用同一个 thread_id，助手应该记得刚才研究了 RAG）\n")

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 15}
    result = graph.invoke(
        {"messages": [HumanMessage(content=followup)]},
        config=config,
    )

    # 追问时 report 节点也会跑，取出最后生成的报告
    print(f"📝 助手的回答/报告：")
    print(result.get("report", result["messages"][-1].content[:200]))


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 09 — 毕业项目：LangGraph 研究助手")
    print("=" * 64)
    print("综合 L06-L08 全部技术，把 Agent L09 手写研究助手重做成图。")
    print("映射：agent-lessons/09_capstone")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    print("\n🔧 构建研究助手图（research + tools + report 三节点）...")
    graph = build_research_graph(llm)
    print("✅ 图已编译（含 Checkpointer 记忆）")

    part_1_graph_viz(graph)                 # 图结构可视化
    part_2_research(graph)                   # 自主搜索 + 报告
    part_3_memory(graph)                     # 记忆演示

    print("\n\n" + "=" * 64)
    print("🎉 框架课程全部完成！")
    print("=" * 64)
    print("✅ 毕业项目小结：")
    print("   - StateGraph 三节点图：research（搜索决策）→ tools（执行）→ report（生成）")
    print("   - 条件边替代了 Agent L09 的 'FINAL_REPORT' 字符串检测")
    print("   - 自定义 State 携带 topic + report（不只是 messages）")
    print("   - Checkpointer 让助手跨轮记住对话（L08）")
    print("   - Mermaid 可视化：流程一目了然")
    print("\n   这个项目可以写进简历 😊")
    print("=" * 64)


if __name__ == "__main__":
    main()
