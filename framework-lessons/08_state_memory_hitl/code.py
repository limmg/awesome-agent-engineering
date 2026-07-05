"""
Lesson 08 — 状态、记忆与人机协作（HITL）
=========================================
LangGraph 的杀手锏：Checkpointer（状态自动持久化）+ interrupt（人机协作）。

两个实验：
  ① 跨轮记忆：同 thread_id 记住上下文，不同 thread_id 失忆（对比 Agent L05 手写 messages）
  ② 人机协作：花钱工具执行前 interrupt 暂停 → Command(resume) 恢复（手写做不到）

映射：agent-lessons/05_memory（手写 messages 管理 + 三策略）

运行：python framework-lessons/08_state_memory_hitl/code.py
"""
# 消除 langchain-community 的 sunset 警告（L01 README 已讲过背景）
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")

import os

from dotenv import load_dotenv

# === LangChain + LangGraph 组件 ===
from langchain_community.chat_models import ChatZhipuAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver       # ⭐ 内存检查点（状态持久化）
from langgraph.types import interrupt, Command             # ⭐ interrupt 暂停 + Command 恢复

CHAT_MODEL = "glm-4"          # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 工具定义：一个"花钱"工具（演示 HITL 审批）
# ════════════════════════════════════════════════════════════
@tool
def spend_money(amount: int, item: str) -> str:
    """花钱购买物品。当用户要求买东西、消费、付款时使用。

    Args:
        amount: 金额（元）
        item: 要购买的物品名
    """
    return f"✅ 已花费 {amount} 元购买 {item}"


TOOLS = [spend_money]


# ════════════════════════════════════════════════════════════
# 实验①：跨轮记忆（Checkpointer + thread_id）
# ════════════════════════════════════════════════════════════
def build_simple_graph(llm):
    """一个最简图（无工具，纯对话），用来演示记忆。

    对比 Agent L05：你手写 messages.append() 维护历史，每轮手动传全部 messages。
    这里 Checkpointer 自动存档，同 thread_id 自动带历史。
    """
    def call_model(state):
        return {"messages": [llm.invoke(state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", call_model)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    # ⭐ 关键：编译时挂上 Checkpointer，State 自动存档
    return builder.compile(checkpointer=MemorySaver())


def experiment_1_memory(llm):
    print("\n" + "═" * 64)
    print("实验①：跨轮记忆（Checkpointer + thread_id）")
    print("═" * 64)

    graph = build_simple_graph(llm)

    # ── 同一 thread_id：应记住上下文 ──
    cfg_same = {"configurable": {"thread_id": "user-A"}}
    print("\n【同一 thread_id='user-A'（应记住）】")

    r1 = graph.invoke(
        {"messages": [HumanMessage(content="我叫张三，请记住我的名字。")]},
        config=cfg_same,
    )
    print(f"  第1轮 用户：我叫张三")
    print(f"  第1轮 助手：{r1['messages'][-1].content[:40]}")

    r2 = graph.invoke(
        {"messages": [HumanMessage(content="我叫什么名字？")]},
        config=cfg_same,   # 同 thread_id → 自动带第1轮的历史
    )
    print(f"  第2轮 用户：我叫什么名字？")
    print(f"  第2轮 助手：{r2['messages'][-1].content[:40]}")

    # ── 不同 thread_id：应失忆 ──
    cfg_diff = {"configurable": {"thread_id": "user-B"}}
    print("\n【不同 thread_id='user-B'（应失忆）】")
    r3 = graph.invoke(
        {"messages": [HumanMessage(content="我叫什么名字？")]},
        config=cfg_diff,   # 不同 thread_id → 全新会话，没有历史
    )
    print(f"  助手：{r3['messages'][-1].content[:50]}")

    print("""
👉 对比 Agent L05 手写：
   手写：messages=[] 全程手动 append，多用户要手写字典路由。
   框架：同 thread_id 自动共享 State（记忆延续），不同 thread_id 自动隔离。
   Checkpointer 在每次节点执行后自动存档——你不用手动管 messages 了。
""")


# ════════════════════════════════════════════════════════════
# 实验②：人机协作（interrupt + Command resume）
# ════════════════════════════════════════════════════════════
def build_hitl_graph(llm):
    """带人机审批的 Agent 图。

    和 L06 的图几乎一样（agent + tools + 条件边 + 回路），
    区别：tools 节点在执行前先 interrupt 暂停，等人确认。
    """
    llm_with_tools = llm.bind_tools(TOOLS)

    def call_model(state):
        return {"messages": [llm_with_tools.invoke(state["messages"])]}

    # ⭐ 关键：自定义 tools 节点，执行前 interrupt 问人
    def call_tools_with_approval(state):
        last_msg = state["messages"][-1]
        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return {"messages": []}

        # ── interrupt：图在这里暂停，把信息交给外部 ──
        approval = interrupt({
            "question": "⚠️ Agent 想执行以下操作，是否批准？",
            "tool_calls": [
                {"name": tc["name"], "args": tc["args"]}
                for tc in tool_calls
            ],
        })
        # interrupt() 的返回值 = 外部用 Command(resume=...) 传进来的值

        if approval == "yes":
            # 批准 → 用 ToolNode 执行
            print("  → 用户批准，执行工具")
            return ToolNode(TOOLS).invoke({"messages": state["messages"]})
        else:
            # 拒绝 → 告诉 Agent 用户拒绝了
            print("  → 用户拒绝")
            return {"messages": [HumanMessage(content="用户拒绝了此次操作。")]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", call_tools_with_approval)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    # ⭐ interrupt 需要 Checkpointer（暂停后要恢复状态）
    return builder.compile(checkpointer=MemorySaver())


def experiment_2_hitl(llm):
    print("\n" + "═" * 64)
    print("实验②：人机协作（interrupt 暂停 → Command 恢复）")
    print("═" * 64)

    graph = build_hitl_graph(llm)
    config = {"configurable": {"thread_id": "hitl-demo"}}

    # ── 第 1 次 invoke：跑到 interrupt 暂停 ──
    print("\n【第1次 invoke】用户：帮我花 100 元买咖啡")
    print("（图会跑到 tools 节点的 interrupt 处暂停）\n")
    result = graph.invoke(
        {"messages": [HumanMessage(content="帮我花 100 元买咖啡")]},
        config=config,
    )

    # 检查是否暂停了
    if "__interrupt__" in result:
        interrupt_info = result["__interrupt__"][0].value
        print(f"⏸️  图已暂停！interrupt 信息：")
        print(f"   {interrupt_info['question']}")
        for tc in interrupt_info["tool_calls"]:
            print(f"   → {tc['name']}({tc['args']})")

        # ── 第 2 次 invoke：用户确认，用 Command(resume=) 恢复 ──
        print("\n【第2次 invoke】用 Command(resume='yes') 恢复，批准执行")
        result2 = graph.invoke(Command(resume="yes"), config=config)
        print(f"\n🤖 最终结果：{result2['messages'][-1].content[:60]}")
    else:
        # 模型没调工具，直接回答了
        print(f"🤖 模型直接回答（没触发工具）：{result['messages'][-1].content[:60]}")

    print("""
👉 对比手写：
   Agent L05/L03 的 for 循环里塞 input() 会破坏自动化、无法上生产。
   LangGraph 的 interrupt 是声明式的：
     - 图在指定节点暂停，状态被 Checkpointer 安全保存
     - 外部用 Command(resume=) 恢复，从暂停处继续
     - 生产环境可以把"暂停"接前端按钮、审批系统……
   这是手写循环几乎做不到优雅实现的事——图的杀手锏。
""")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 08 — 状态、记忆与人机协作（HITL）")
    print("=" * 64)
    print("LangGraph 杀手锏：Checkpointer 状态持久化 + interrupt 人机协作。")
    print("映射：agent-lessons/05_memory（手写 messages 管理）")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    experiment_1_memory(llm)    # 跨轮记忆
    experiment_2_hitl(llm)      # 人机协作

    print("=" * 64)
    print("✅ 状态与 HITL 小结：")
    print("   - Checkpointer：State 自动存档，thread_id 隔离会话")
    print("   - 同 thread_id = 记忆延续；不同 = 互相隔离")
    print("   - interrupt + Command(resume)：优雅的人机协作（手写做不到）")
    print("   - 记忆原理仍是 Agent L05 那套，框架是自动化封装")
    print("=" * 64)


if __name__ == "__main__":
    main()
