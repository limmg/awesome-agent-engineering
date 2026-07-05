"""
Lesson 06 — LangGraph 基础：StateGraph 重写 ReAct
===================================================
把 Agent L03 手写的 while 循环 ReAct，用 LangGraph 的 StateGraph 重写成图。

三个部分：
  ① 用 StateGraph 重写 ReAct（agent + tools 两节点 + 条件边）
  ② 打印图结构，对比手写循环
  ③ 跑多步任务（多次工具调用），看图自动循环

映射：agent-lessons/03_react_loop（手写 run_react_agent while 循环）

运行：python framework-lessons/06_langgraph_basics/code.py
"""
# 消除 langchain-community 的 sunset 警告（L01 README 已讲过背景）
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")

import os
from datetime import datetime

from dotenv import load_dotenv

# === LangChain + LangGraph 组件 ===
from langchain_community.chat_models import ChatZhipuAI
from langchain_core.tools import tool                         # @tool 装饰器（L07 详讲，这里先用）
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition       # 预置的工具节点 + 路由函数

CHAT_MODEL = "glm-4"          # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 第 1 步：定义工具（复用 Agent L03 的三个工具）
# ════════════════════════════════════════════════════════════
# 对比 Agent L03：你手写了 TOOLS_SPEC（35 行 JSON Schema）+ execute_function（10 行调度器）
# 这里用 @tool 装饰器：docstring + 类型注解自动生成 schema（L07 详讲原理）


@tool
def get_current_time() -> str:
    """获取当前的日期和时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculator(expression: str) -> str:
    """计算数学表达式。expression 如 '12 * 34' 或 '100 / 7'。"""
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：表达式包含非法字符"
        return str(eval(expression))
    except ZeroDivisionError:
        return "错误：除数不能为 0"
    except Exception as e:
        return f"计算错误：{e}"


@tool
def string_length(text: str) -> str:
    """计算字符串的字符数。"""
    return f"'{text}' 的长度是 {len(text)} 个字符"


TOOLS = [get_current_time, calculator, string_length]


# ════════════════════════════════════════════════════════════
# 第 2 步：定义节点函数
# ════════════════════════════════════════════════════════════
def create_agent_node(llm_with_tools):
    """创建 agent 节点函数。

    节点就是一个 (state) -> state_update 的函数。
    对比 Agent L03 手写：response = client.chat.completions.create(messages=..., tools=...)
    """
    def call_model(state: MessagesState):
        # state 是 {"messages": [...]}，把整个对话历史喂给模型
        response = llm_with_tools.invoke(state["messages"])
        # 返回的 {"messages": [response]} 会被自动追加进 state["messages"]
        return {"messages": [response]}
    return call_model


# ════════════════════════════════════════════════════════════
# 第 3 步：组装 StateGraph（本课核心）
# ════════════════════════════════════════════════════════════
def build_graph(llm):
    """用 StateGraph 把 Agent L03 的 while 循环重写成图。

    对比 Agent L03 的 run_react_agent：
      for step in range(max_steps):       ← 图的回路 tools → agent
          if msg.tool_calls: ...          ← 条件边 tools_condition
          execute_function(name, args)    ← ToolNode 节点
          messages.append(...)            ← State 自动追加
    """
    # 把工具绑定到模型（让模型知道有哪些工具可用）
    llm_with_tools = llm.bind_tools(TOOLS)

    # ① 创建图的构建器，指定 State 类型
    builder = StateGraph(MessagesState)

    # ② 加节点
    builder.add_node("agent", create_agent_node(llm_with_tools))
    builder.add_node("tools", ToolNode(TOOLS))   # ToolNode 替代你手写的 execute_function

    # ③ 加边：入口 → agent
    builder.add_edge(START, "agent")

    # ④ 加条件边：agent 执行完后，根据模型返回决定去哪
    #    tools_condition 自动判断"最后一条消息有没有 tool_calls"
    #    有 → 去 "tools" 节点；没有 → 去 END（给出最终答案）
    builder.add_conditional_edges("agent", tools_condition)

    # ⑤ 加回路：tools 执行完，回到 agent 再调模型（这就是 while 循环！）
    builder.add_edge("tools", "agent")

    # ⑥ 编译成可执行的图
    graph = builder.compile()
    return graph


# ════════════════════════════════════════════════════════════
# 部分①：构建图并跑一个简单任务
# ════════════════════════════════════════════════════════════
def part_1_simple_task(graph):
    print("\n" + "═" * 64)
    print("部分①：用图跑一个工具调用任务")
    print("═" * 64)

    question = "查询北京的天气"  # 占位，实际用下面的
    question = "现在是几点？"
    print(f"\n问题：{question}")

    # 运行图：传入初始 messages
    result = graph.invoke({"messages": [HumanMessage(content=question)]})

    # 打印消息轨迹——这对应你 Agent L03 打印的 Thought/Action/Observation
    print(f"\n消息轨迹（共 {len(result['messages'])} 条）：")
    for i, msg in enumerate(result["messages"]):
        role = type(msg).__name__
        tc = getattr(msg, "tool_calls", None)
        content_preview = str(msg.content).replace("\n", " ")[:50]
        print(f"  [{i}] {role}: {content_preview}")
        if tc:
            for call in tc:
                print(f"        ↳ 工具调用: {call['name']}({call['args']})")

    print("\n👉 对比 Agent L03：")
    print("   手写要在 for 循环里手动调模型、判断 tool_calls、执行、塞回 messages。")
    print("   图把这些变成节点+边，.invoke() 自动游走整张图。")


# ════════════════════════════════════════════════════════════
# 部分②：打印图结构（对比手写循环）
# ════════════════════════════════════════════════════════════
def part_2_graph_structure(graph):
    print("\n" + "═" * 64)
    print("部分②：图的结构（对比手写 while 循环）")
    print("═" * 64)

    # 打印图里有哪些节点
    g = graph.get_graph()
    print("\n图中的节点：")
    for node_id, node in g.nodes.items():
        print(f"  • {node_id}")

    print("\n图中的边（连线）：")
    for edge in g.edges:
        src = edge.source
        tgt = edge.target
        cond = f" (条件: {edge.condition})" if hasattr(edge, "condition") and edge.condition else ""
        print(f"  • {src} → {tgt}{cond}")

    print("""
┌─────────────────────────────────────────┐
│  你手写的 Agent L03 ReAct 循环 = 这张图  │
│                                         │
│         ┌───────────┐                   │
│         │     ▼     │                   │
│      ┌──┴────┐  有tool_calls  ┌──────┐  │
│START─▶│ agent │───────────────▶│tools │  │
│      │(调模型)│                │(执行)│  │
│      └──┬────┘                └──┬───┘  │
│         │ 没tool_calls    ◀──────┘      │
│         ▼         (回路)               │
│        END                              │
└─────────────────────────────────────────┘

  • agent 节点 = client.chat.completions.create(...)
  • tools 节点 = execute_function(...)（ToolNode 替你写了）
  • 条件边 = if msg.tool_calls: ... else: ...
  • tools→agent 回路 = for 循环的"再来一轮"
  • END = return（终止）
""")


# ════════════════════════════════════════════════════════════
# 部分③：多步任务（看图自动循环多轮）
# ════════════════════════════════════════════════════════════
def part_3_multi_step(graph):
    print("\n" + "═" * 64)
    print("部分③：多步任务（图自动循环多轮）")
    print("═" * 64)

    # 这个任务需要多轮：查时间 → 计算 → 回答
    question = "现在是几点？把当前的小时数和分钟数相加，结果除以 7，余数是多少？"
    print(f"\n问题：{question}")
    print("（这个任务需要：查时间 → 提取小时分钟 → 计算 → 回答，图会自动循环）\n")

    result = graph.invoke({"messages": [HumanMessage(content=question)]})

    print(f"消息轨迹（共 {len(result['messages'])} 条，多条 = 多轮循环）：")
    for i, msg in enumerate(result["messages"]):
        role = type(msg).__name__
        tc = getattr(msg, "tool_calls", None)
        content_preview = str(msg.content).replace("\n", " ")[:60]
        print(f"  [{i}] {role}: {content_preview}")
        if tc:
            for call in tc:
                print(f"        ↳ 工具调用: {call['name']}({call['args']})")

    final = result["messages"][-1].content
    print(f"\n🤖 最终答案：{final[:100]}")
    print("\n👉 对比 Agent L03：")
    print("   手写要 for 循环 + 手动判断终止条件 + 手动管 messages。")
    print("   图的 .invoke() 自动完成了多轮循环——回路 tools→agent 替代了 for。")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 06 — LangGraph 基础：StateGraph 重写 ReAct")
    print("=" * 64)
    print("把 Agent L03 手写的 while 循环，用 StateGraph 重写成图。")
    print("映射：agent-lessons/03_react_loop")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    # 构建图
    print("\n🔧 构建 StateGraph（agent + tools 两节点 + 条件边 + 回路）...")
    graph = build_graph(llm)
    print("✅ 图已编译")

    part_1_simple_task(graph)       # 简单工具调用
    part_2_graph_structure(graph)   # 图结构对比
    part_3_multi_step(graph)        # 多步任务

    print("\n" + "=" * 64)
    print("✅ LangGraph 基础小结：")
    print("   - Agent 本质是状态机 → 用图表达")
    print("   - StateGraph 三要素：State / Node / Edge（含条件边）")
    print("   - ToolNode + tools_condition 替代你手写的 execute_function + if tool_calls")
    print("   - 图的回路 tools→agent 替代了 while 循环")
    print("   - 原理没变（仍是 ReAct），改变的是表达方式：命令式 → 声明式")
    print("=" * 64)


if __name__ == "__main__":
    main()
