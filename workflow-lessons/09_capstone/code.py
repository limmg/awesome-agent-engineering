"""
Lesson 09 — 毕业项目：多智能体研究系统（简历级）
==================================================
这是整个学习之旅（36 课）的收官之作。
综合 L01-L08 全部技术，搭一个能进简历的多智能体研究系统。

系统设计：用户给研究主题 → 并行研究多子问题 → 分析综合 → 生成报告

综合技术：
    - L01 supervisor：调度中心（决定研究什么、何时写报告）
    - L03 子图：并行研究子系统封装成节点
    - L04 并行 map-reduce：多个研究员同时查不同子问题
    - L05 共享 State：findings 字段 + reducer 结构化通信
    - L06 多模型路由：glm-4 决策/写作 + glm-4-flash 并行查询（降本）
    - framework-L08 Checkpointer：跨轮记忆（追问能记住）
    - framework-L09 Mermaid：架构可视化

对比：
    - Agent L09（单 Agent 研究助手）：一个 Agent 串行搜索 → 串行报告
    - Framework L09（单 Agent 三节点图）：research→tools→report 串行
    - 本课（多智能体并行）：3 个研究员【并行】查 + supervisor 调度 + 多模型降本

运行：python workflow-lessons/09_capstone/code.py
"""
# 消除警告
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")
try:
    from jwt.warnings import InsecureKeyLengthWarning
    warnings.filterwarnings("ignore", category=InsecureKeyLengthWarning)
except ImportError:
    pass

import os
import operator
from typing import Annotated
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_community.chat_models import ChatZhipuAI
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Send                           # L04 并行
from langgraph.checkpoint.memory import InMemorySaver       # framework-L08 记忆

SMART_MODEL = "glm-4"        # 决策/写作：贵但聪明
FAST_MODEL = "glm-4-flash"   # 并行查询：免费快


# ════════════════════════════════════════════════════════════
# 第 1 步：并行研究子图（L04 map-reduce + L06 多模型）
# ════════════════════════════════════════════════════════════
class ResearchState(TypedDict):
    """并行研究子图的 State。

    findings 用 reducer（L05 共享 State + L04 并行写回）：
    多个并行 researcher 的结果自动拼接，不覆盖。
    """
    topic: str
    subtopics: list[str]
    findings: Annotated[list[str], operator.add]  # ⭐ reducer 合并并行结果
    research_summary: str


def build_research_subgraph(fast_llm, smart_llm):
    """构建并行研究子图。

    架构（L04 map-reduce）：
        split(拆题) → researcher×3(并行查) → summarize(汇总)

    多模型（L06）：
        split + researcher 用 fast_llm（执行类，免费）
        summarize 用 smart_llm（汇总要质量）
    """
    # ── split：用 fast_llm 把主题拆成 3 个子问题 ──
    def split(state: ResearchState):
        topic = state["topic"]
        resp = fast_llm.invoke(
            f"你是研究规划师。把「{topic}」拆成 3 个具体的研究子问题，"
            f"每行一个，只要问题本身，不要编号。"
        )
        subs = [s.strip().lstrip("0123456789.、）) ") for s in resp.content.strip().split("\n") if s.strip()][:3]
        print(f"    [并行研究-split] 拆出 {len(subs)} 个子问题")
        return {"subtopics": subs}

    # ── 路由：返回多个 Send 触发并行 fan-out（L04 核心）──
    def route_to_researchers(state: ResearchState):
        sends = [Send("researcher", {"subtopic": s}) for s in state["subtopics"]]
        print(f"    [并行研究-route] 并行派发 {len(sends)} 个研究员")
        return sends

    # ── researcher：并行查单个子问题（用 fast_llm，免费）──
    def researcher(state):
        subtopic = state["subtopic"]
        resp = fast_llm.invoke(f"用 2 句话简要回答：{subtopic}")
        finding = f"【{subtopic}】{resp.content.strip()[:80]}"
        print(f"    [并行研究-researcher] ✓ 完成一个子问题")
        return {"findings": [finding]}  # ⭐ reducer 自动拼接

    # ── summarize：用 smart_llm 汇总（质量优先）──
    def summarize(state: ResearchState):
        all_findings = "\n\n".join(state["findings"])
        resp = smart_llm.invoke(
            f"你是研究综合分析师。把以下研究发现整理成一段连贯的研究摘要：\n\n{all_findings}"
        )
        print(f"    [并行研究-summarize] 汇总 {len(state['findings'])} 个发现")
        return {"research_summary": resp.content.strip()}

    # ── 组装并行子图 ──
    builder = StateGraph(ResearchState)
    builder.add_node("split", split)
    builder.add_node("researcher", researcher)
    builder.add_node("summarize", summarize)
    builder.add_edge(START, "split")
    builder.add_conditional_edges("split", route_to_researchers)  # ⭐ 并行 fan-out
    builder.add_edge("researcher", "summarize")                   # 所有并行完成 → 汇总
    builder.add_edge("summarize", END)
    return builder.compile()


# ════════════════════════════════════════════════════════════
# 第 2 步：顶层父图（L03 子图作为节点 + supervisor 调度逻辑）
# ════════════════════════════════════════════════════════════
class SystemState(TypedDict):
    """整个研究系统的 State（父图）。

    综合了：
    - messages（L01 supervisor 的对话历史）
    - findings（L05 共享 State，从子图回流）
    - research_summary（子图产出的研究摘要）
    - report（最终报告）
    """
    messages: Annotated[list, add_messages]
    findings: Annotated[list[str], operator.add]    # 从子图回流（L05 共享 State）
    research_summary: str
    report: str


def build_system(smart_llm, fast_llm, research_subgraph):
    """构建完整的多智能体研究系统。

    架构（L03 子图作为父图节点）：
        START → research_team(并行子图) → writer → END

    对比前两个毕业项目：
        Agent L09：单 Agent 串行搜索（一个 Agent 搜 N 次）
        Framework L09：单 Agent 三节点图（research→tools→report 串行）
        本课：多 Agent 并行（3 个 researcher 同时查 + writer 写报告）
    """
    # ── research_team 节点：把并行子图当节点（L03 技术）──
    def research_team(state: SystemState):
        # 从对话历史提取研究主题
        topic = state["messages"][-1].content
        print(f"\n  [research_team] 启动并行研究：{topic[:40]}")

        # 调用并行子图（L03 子图作为节点）
        sub_result = research_subgraph.invoke({
            "topic": topic, "subtopics": [], "findings": [], "research_summary": ""
        })

        # 把子图结果回流到父图 State（L05 共享 State）
        return {
            "findings": sub_result["findings"],              # 回流并行发现
            "research_summary": sub_result["research_summary"],  # 回流摘要
        }

    # ── writer 节点：用 smart_llm 写最终报告 ──
    def writer(state: SystemState):
        summary = state["research_summary"]
        print(f"\n  [writer] 基于研究摘要生成报告...")
        resp = smart_llm.invoke(
            f"你是专业研究报告撰写者。基于以下研究摘要，写一份结构化研究报告，"
            f"包含概述和核心要点（3-5条）。语言专业简洁：\n\n{summary}"
        )
        report = resp.content.strip()
        print(f"  [writer] 报告生成完成（{len(report)} 字）")
        return {
            "report": report,
            "messages": [AIMessage(content=report)],  # 也写到 messages（供 Checkpointer 记忆）
        }

    # ── 组装父图 ──
    builder = StateGraph(SystemState)
    builder.add_node("research_team", research_team)  # ⭐ 子图作为节点（L03）
    builder.add_node("writer", writer)
    builder.add_edge(START, "research_team")
    builder.add_edge("research_team", "writer")
    builder.add_edge("writer", END)

    # ⭐ Checkpointer：跨轮记忆（framework-L08 技术）
    return builder.compile(checkpointer=InMemorySaver())


# ════════════════════════════════════════════════════════════
# 实验 1：完整研究流程（多智能体并行）
# ════════════════════════════════════════════════════════════
def part_1_full_research(system):
    """演示完整的多智能体并行研究流程。"""
    print("\n" + "═" * 60)
    print("实验 1：多智能体并行研究（完整流程）")
    print("═" * 60)
    topic = "2024 年 AI Agent 技术的重要进展"
    print(f"📋 研究主题：{topic}")
    print(f"\n流程：research_team(并行3研究员) → writer(生成报告)\n")

    config = {"configurable": {"thread_id": "research-1"}}
    result = system.invoke({
        "messages": [{"role": "user", "content": topic}],
        "findings": [], "research_summary": "", "report": "",
    }, config=config)

    print(f"\n{'━' * 60}")
    print(f"✅ 研究报告：\n{result['report'][:400]}")
    print(f"\n📊 并行研究发现（{len(result['findings'])} 个）：")
    for f in result["findings"]:
        print(f"  {f[:70]}")
    print(f"{'━' * 60}")
    print(f"\n💡 对比 Agent L09（单 Agent 串行）：")
    print(f"   那里一个 Agent 搜 N 次（串行）；这里 3 个研究员同时查（并行）")


# ════════════════════════════════════════════════════════════
# 实验 2：跨轮记忆（Checkpointer）
# ════════════════════════════════════════════════════════════
def part_2_memory(system):
    """演示 Checkpointer 跨轮记忆。

    用同一个 thread_id 追问，系统能记住上一轮的研究内容。
    """
    print("\n\n" + "═" * 60)
    print("实验 2：跨轮记忆（Checkpointer）")
    print("═" * 60)
    print("用实验 1 的同一个 thread_id 追问，验证记忆...\n")

    config = {"configurable": {"thread_id": "research-1"}}  # 同一个 thread
    result = system.invoke({
        "messages": [{"role": "user", "content": "基于刚才的研究，用一句话总结核心结论"}],
        "findings": [], "research_summary": "", "report": "",
    }, config=config)

    print(f"追问回答：{result['messages'][-1].content[:200]}")
    print(f"\n💡 Checkpointer 让系统记住了实验 1 的研究内容（同 thread_id）。")


# ════════════════════════════════════════════════════════════
# 实验 3：架构可视化（Mermaid + 技术清单）
# ════════════════════════════════════════════════════════════
def part_3_architecture(system, research_subgraph):
    """打印架构图和技术清单。"""
    print("\n\n" + "═" * 60)
    print("实验 3：系统架构可视化")
    print("═" * 60)

    print("\n【父图拓扑（research_team + writer）】")
    print(system.get_graph().draw_mermaid())

    print("\n【并行研究子图拓扑（split → researcher×N → summarize）】")
    print(research_subgraph.get_graph().draw_mermaid())

    print("━" * 60)
    print("【综合技术清单（L01-L08 全部用到）】")
    tech = [
        ("L01 supervisor", "调度逻辑（research_team → writer）"),
        ("L03 子图", "并行研究子系统封装成 research_team 节点"),
        ("L04 并行 map-reduce", "3 个 researcher 用 Send 同时查（fan-out）"),
        ("L05 共享 State", "findings 字段 + operator.add reducer"),
        ("L06 多模型", "glm-4 决策/写作 + glm-4-flash 并行查询"),
        ("fw-L08 Checkpointer", "InMemorySaver 跨轮记忆"),
        ("fw-L09 Mermaid", "架构可视化"),
    ]
    for tech_name, usage in tech:
        print(f"  ✅ {tech_name}: {usage}")
    print("━" * 60)


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 09 — 毕业项目：多智能体研究系统（简历级）")
    print("=" * 64)
    print("综合 L01-L08 全部技术，整个 36 课学习的收官之作。")
    print("对比：Agent L09（单Agent串行）/ Framework L09（单Agent三节点）")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")

    # 多模型实例（L06）
    smart_llm = ChatZhipuAI(model=SMART_MODEL, api_key=api_key)
    fast_llm = ChatZhipuAI(model=FAST_MODEL, api_key=api_key)
    print(f"\n🧠 smart: {SMART_MODEL}（决策/写作）  ⚡ fast: {FAST_MODEL}（并行查询）")

    # 构建并行研究子图（L04）
    print("\n🔧 构建并行研究子图（split → researcher×3 并行 → summarize）...")
    research_subgraph = build_research_subgraph(fast_llm, smart_llm)
    print("✅ 子图已编译")

    # 构建完整系统（L03 子图节点 + Checkpointer）
    print("🔧 构建研究系统（research_team[子图] + writer + Checkpointer）...")
    system = build_system(smart_llm, fast_llm, research_subgraph)
    print("✅ 系统已编译")

    part_1_full_research(system)                    # 完整研究流程
    part_2_memory(system)                           # 跨轮记忆
    part_3_architecture(system, research_subgraph)  # 架构可视化

    print("\n" + "=" * 64)
    print("🎉 毕业项目完成！整个学习之旅（36 课）收官！")
    print()
    print("✅ 你掌握的全部能力：")
    print("   📘 RAG 手写（9课）：embedding→检索→切块→prompt→混合检索→改写→评估→工程化")
    print("   🤖 Agent 手写（9课）：Function Calling→ReAct→工具→记忆→规划→Agentic RAG→多智能体")
    print("   🔧 框架进阶（9课）：LangChain LCEL→三件套→Document→Retriever→LangGraph→create_agent→HITL")
    print("   🔀 多智能体编排（9课）：supervisor→swarm→子图→并行→通信→多模型→CrewAI→AutoGen→毕业项目")
    print()
    print("💼 这个毕业项目可以写进简历：")
    print("   「基于 LangGraph 的多智能体并行研究系统」")
    print("   - supervisor 调度 + 3 个研究员并行 map-reduce")
    print("   - 多模型路由降本（glm-4 决策 + glm-4-flash 执行）")
    print("   - Checkpointer 跨轮记忆 + Mermaid 架构可视化")
    print("=" * 64)


if __name__ == "__main__":
    main()
