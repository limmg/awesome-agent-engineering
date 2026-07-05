"""
Lesson 05 — 共享状态通信：从字符串到结构化
============================================
前 4 课里 Agent 之间用各种方式交换信息：handoff（L02）、Send（L04）。
本课系统对比【三种通信机制】，看清它们的差别和适用场景。

核心问题：
    Agent L08 手写时用 task = f"{task}\\n(审查意见：{verdict})" 字符串拼接传信息——
    松散、易丢信息。框架提供更结构化的通信方式。

三种通信机制：
  ① 消息传递（手写 L08 的方式）：Agent 输出拼进下一个 prompt —— 松散
  ② 共享 State：多 Agent 读写同一字段 —— 结构化、可追溯
  ③ 黑板模式：共享一个"知识池"，Agent 各取所需 —— 解耦

三个部分（同一任务，三种通信各做一遍）：
  ① 消息传递版（复刻手写 L08 的字符串拼接）
  ② 共享 State 版（用 TypedDict 字段传递）
  ③ 黑板模式版（用 knowledge 池 + reducer）

映射：agent-lessons/08_multi_agent（手写字符串拼接传信息）
运行：python workflow-lessons/05_shared_state/code.py
"""
# 消除 langchain-community 的 sunset 警告 + jwt 密钥长度警告（都不影响使用）
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
from langgraph.graph import StateGraph, START, END

CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 实验前置：构建一个简单的"规划-执行-总结"任务（三种通信各实现一次）
# 任务：给定一个研究主题，规划→执行→总结
# ════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# 实验 1：消息传递（复刻手写 L08 的字符串拼接）
# ════════════════════════════════════════════════════════════
def part_1_message_passing(llm):
    """消息传递：Agent 的输出拼进下一个 Agent 的 prompt。

    这就是 Agent L08 手写的方式：
        task = f"{task}\\n(审查意见：{verdict})"  ← 字符串拼接
    本实验复刻这种风格，让学习者看清它的局限。
    """
    print("\n" + "─" * 60)
    print("实验 1：消息传递（复刻手写 L08 的字符串拼接）")
    print("─" * 60)
    topic = "AI Agent 的应用场景"
    print(f"📋 研究主题：{topic}\n")

    # ── 规划者：输出计划（字符串）──
    plan_resp = llm.invoke(f"主题「{topic}」，用1句话给出研究计划。")
    plan = plan_resp.content.strip()
    print(f"  [规划者] 输出计划：{plan[:50]}")

    # ── 执行者：把规划者的输出【字符串拼进 prompt】──
    # ⚠️ 这就是手写 L08 的方式——信息靠拼接传递
    exec_resp = llm.invoke(f"基于以下计划执行（给出2个要点）：\n{plan}")
    execution = exec_resp.content.strip()
    print(f"  [执行者] 拼接计划到prompt→输出：{execution[:50]}")

    # ── 总结者：把执行者的输出【字符串拼进 prompt】──
    summary_resp = llm.invoke(f"总结以下内容成1句话：\n{execution}")
    summary = summary_resp.content.strip()
    print(f"  [总结者] 拼接执行到prompt→输出：{summary[:50]}")

    print(f"\n⚠️ 问题：信息靠 f-string 拼接传递，")
    print(f"   如果中间某步输出太长会被截断，格式混乱，且无法追溯完整历史。")
    print(f"   （这正是手写 L08 task = f'{{task}}\\n(审查意见:...)' 的局限）")


# ════════════════════════════════════════════════════════════
# 实验 2：共享 State（用 TypedDict 字段传递，结构化）
# ════════════════════════════════════════════════════════════
class SharedState(TypedDict):
    """共享 State：每个 Agent 读写固定字段，结构化、可追溯。

    对比消息传递：
        消息传递：信息藏在 prompt 字符串里，无结构
        共享 State：信息存在固定字段（plan/execution/summary），有结构
    """
    topic: str
    plan: str        # 规划者写
    execution: str   # 执行者写（读 plan）
    summary: str     # 总结者写（读 execution）


def part_2_shared_state(llm):
    """共享 State：Agent 读写 State 的固定字段。

    对比手写 L08：信息存在 State 字段里，而不是拼进字符串。
    每个 Agent 明确知道"我读哪个字段、写哪个字段"——结构化、可追溯。
    """
    print("\n\n" + "─" * 60)
    print("实验 2：共享 State（结构化字段传递）")
    print("─" * 60)
    topic = "AI Agent 的应用场景"
    print(f"📋 研究主题：{topic}\n")

    def planner(state: SharedState):
        # 读 topic，写 plan
        resp = llm.invoke(f"主题「{state['topic']}」，用1句话给出研究计划。")
        plan = resp.content.strip()
        print(f"  [规划者] 读 topic→写 plan：{plan[:50]}")
        return {"plan": plan}  # 写到固定字段 plan

    def executor(state: SharedState):
        # 读 plan，写 execution（不拼字符串，读固定字段）
        resp = llm.invoke(f"基于以下计划执行（给出2个要点）：\n{state['plan']}")
        execution = resp.content.strip()
        print(f"  [执行者] 读 plan→写 execution：{execution[:50]}")
        return {"execution": execution}

    def summarizer(state: SharedState):
        resp = llm.invoke(f"总结以下内容成1句话：\n{state['execution']}")
        summary = resp.content.strip()
        print(f"  [总结者] 读 execution→写 summary：{summary[:50]}")
        return {"summary": summary}

    builder = StateGraph(SharedState)
    builder.add_node("planner", planner)
    builder.add_node("executor", executor)
    builder.add_node("summarizer", summarizer)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "executor")
    builder.add_edge("executor", "summarizer")
    builder.add_edge("summarizer", END)
    graph = builder.compile()

    result = graph.invoke({"topic": topic, "plan": "", "execution": "", "summary": ""})

    print(f"\n✅ 优势：信息存在固定字段（plan/execution/summary），")
    print(f"   每步读什么写什么清清楚楚，最后 result 字典里能追溯全部中间结果：")
    print(f"   plan = {result['plan'][:40]}")
    print(f"   execution = {result['execution'][:40]}")
    print(f"   summary = {result['summary'][:40]}")


# ════════════════════════════════════════════════════════════
# 实验 3：黑板模式（共享知识池，Agent 各取所需）
# ════════════════════════════════════════════════════════════
class BlackboardState(TypedDict):
    """黑板 State：knowledge 是共享知识池，所有 Agent 往这里追加。

    对比共享 State：
        共享 State：每个字段有固定读写者（plan 只有 planner 写）
        黑板模式：所有 Agent 都读写同一个 knowledge 池，不区分谁写什么
    """
    topic: str
    knowledge: Annotated[list[str], operator.add]  # ⭐ 黑板：reducer 自动拼接
    answer: str


def part_3_blackboard(llm):
    """黑板模式：所有 Agent 读写同一个 knowledge 知识池。

    核心特点：Agent 之间【解耦】——
    每个 Agent 不需要知道"谁在我前面、谁在我后面"，
    只管"往黑板写知识、从黑板读知识"。

    这就像办公室里的白板：每个人往上面写，每个人都能看，不需要互相喊话。
    """
    print("\n\n" + "─" * 60)
    print("实验 3：黑板模式（共享知识池，解耦）")
    print("─" * 60)
    topic = "AI Agent 的应用场景"
    print(f"📋 研究主题：{topic}\n")

    def researcher(state: BlackboardState):
        # 往黑板写"事实"
        resp = llm.invoke(f"主题「{state['topic']}」，给出2个关键事实，每条15字内。")
        fact = resp.content.strip()
        print(f"  [研究员] 往黑板写事实：{fact[:40]}")
        return {"knowledge": [f"【事实】{fact}"]}

    def analyst(state: BlackboardState):
        # 读黑板全部，写"分析"
        all_knowledge = "\n".join(state.get("knowledge", []))
        resp = llm.invoke(f"已知信息：\n{all_knowledge}\n给出1句分析（20字内）。")
        analysis = resp.content.strip()
        print(f"  [分析者] 读黑板→写分析：{analysis[:40]}")
        return {"knowledge": [f"【分析】{analysis}"]}

    def writer(state: BlackboardState):
        # 读黑板全部，写最终答案
        all_knowledge = "\n".join(state.get("knowledge", []))
        resp = llm.invoke(f"汇总以下信息成1句话结论：\n{all_knowledge}")
        print(f"  [撰写者] 读黑板全部→写答案")
        return {"answer": resp.content.strip()}

    builder = StateGraph(BlackboardState)
    builder.add_node("researcher", researcher)
    builder.add_node("analyst", analyst)
    builder.add_node("writer", writer)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "analyst")
    builder.add_edge("analyst", "writer")
    builder.add_edge("writer", END)
    graph = builder.compile()

    result = graph.invoke({"topic": topic, "knowledge": [], "answer": ""})

    print(f"\n✅ 黑板最终内容（所有 Agent 的产出都在 knowledge 池里）：")
    for k in result["knowledge"]:
        print(f"   {k[:60]}")
    print(f"\n💡 优势：Agent 之间【完全解耦】——")
    print(f"   研究员不知道分析者存在，分析者不知道撰写者存在，")
    print(f"   它们只跟「黑板」打交道。换掉任何一个 Agent 不影响其他。")


# ════════════════════════════════════════════════════════════
# 三种机制对比总结
# ════════════════════════════════════════════════════════════
def part_4_comparison():
    """打印三种通信机制的对比表。"""
    print("\n\n" + "─" * 60)
    print("总结：三种通信机制对比")
    print("─" * 60)
    print("""
┌─────────────┬──────────────────┬──────────────────┬──────────────────┐
│             │  ① 消息传递       │  ② 共享 State     │  ③ 黑板模式       │
│             │  (手写 L08)       │  (本课实验2)      │  (本课实验3)      │
├─────────────┼──────────────────┼──────────────────┼──────────────────┤
│ 怎么传信息   │ 字符串拼进prompt  │ 读写固定字段     │ 读写同一知识池    │
│ 结构化程度   │ 无（纯文本）      │ 有（TypedDict）  │ 有（列表+标签）   │
│ 可追溯性     │ 差（拼着拼着乱了）│ 好（字段分明）   │ 好（黑板留全貌）  │
│ Agent 耦合度 │ 高（要知道格式）  │ 中（要知道字段） │ 低（只管读写池）  │
│ 适合场景     │ 简单/快速原型     │ 固定流程         │ 松耦合/可扩展     │
│ 手写L08用的  │ ✅ 就是这个       │                  │                  │
└─────────────┴──────────────────┴──────────────────┴──────────────────┘
""")
    print("💡 选型建议：")
    print("   - 简单任务/原型：消息传递（最快，但易乱）")
    print("   - 固定流程（规划→执行→审查）：共享 State（结构清晰）")
    print("   - Agent 多/经常增减/松耦合：黑板模式（最灵活）")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 05 — 共享状态通信：从字符串到结构化")
    print("=" * 64)
    print("系统对比三种通信机制，映射手写 L08 的字符串拼接。")
    print("映射：agent-lessons/08_multi_agent（手写消息传递）")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    part_1_message_passing(llm)   # 消息传递（手写 L08 风格）
    part_2_shared_state(llm)      # 共享 State
    part_3_blackboard(llm)        # 黑板模式
    part_4_comparison()           # 三种对比

    print("\n" + "=" * 64)
    print("✅ 共享状态通信小结：")
    print("   - 消息传递（手写L08）：字符串拼接，松散易乱，但最简单")
    print("   - 共享 State：读写固定字段，结构化可追溯，适合固定流程")
    print("   - 黑板模式：共享知识池（reducer 拼接），Agent 解耦，适合可扩展系统")
    print("   - reducer 是共享 State/黑板的基础：解决多 Agent 并发写的冲突")
    print("   - 对比手写 L08：task=f'{task}\\n...' → 结构化字段/黑板")
    print("=" * 64)


if __name__ == "__main__":
    main()
