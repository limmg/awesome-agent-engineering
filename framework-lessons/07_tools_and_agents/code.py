"""
Lesson 07 — 框架级 Agent：Tools + prebuilt Agents
===================================================
把 Agent L02（手写 TOOLS_SPEC）+ L04（工具设计）+ L06（手写 StateGraph）完全框架化。

三个实验：
  ① @tool 自动生成 schema（对比 Agent L04 手写的 TOOLS_SPEC）
  ② create_agent 一行建 Agent（对比 L06 手写的整张图）
  ③ 真实细节：LLM 用工具时可能犯的错（description 仍是灵魂）

映射：agent-lessons/02_function_calling + 04_tool_design + 03_react_loop

运行：python framework-lessons/07_tools_and_agents/code.py
"""
# 消除 langchain-community 的 sunset 警告（L01 README 已讲过背景）
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")

import json
import os
from datetime import datetime

from dotenv import load_dotenv

# === LangChain + LangGraph 组件 ===
from langchain_community.chat_models import ChatZhipuAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
# ⭐ 一行建 Agent 的预置函数
# LangGraph 1.x 的迁移：create_react_agent 已迁移到 langchain.agents.create_agent
#   旧路径：from langchain.prebuilt import create_react_agent  （已弃用，V2.0 移除）
#   新路径：from langchain.agents import create_agent           （推荐）
#   两者功能相同，新路径是 LangChain 1.x 统一 agents 入口的结果
from langchain.agents import create_agent

CHAT_MODEL = "glm-4"          # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 工具定义：用 @tool 装饰器（对比 Agent L04 的手写 TOOLS_SPEC）
# ════════════════════════════════════════════════════════════
# 对比 Agent L02/L04：你要写 函数 + TOOLS_SPEC(JSON) + TOOL_REGISTRY，三份重复
# @tool 只写一份函数，schema 自动从类型注解 + docstring 生成


@tool
def get_current_time() -> str:
    """获取当前的日期和时间。当用户问'现在几点''今天日期'时使用。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculator(expression: str) -> str:
    """计算数学表达式（四则运算）。需要精确计算加减乘除时使用。

    Args:
        expression: 数学表达式，如 '12 * 34' 或 '(1 + 2) * 3'。
            注意：用 ** 表示乘方（如 2**10），不要用 ^（^ 在 Python 里是异或）。
    """
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
    """计算字符串的字符数（长度）。当用户问'XX有几个字''XX多长'时使用。

    Args:
        text: 要计算长度的字符串
    """
    return f"'{text}' 的长度是 {len(text)} 个字符"


TOOLS = [get_current_time, calculator, string_length]


# ════════════════════════════════════════════════════════════
# 实验①：@tool 自动生成 schema
# ════════════════════════════════════════════════════════════
def experiment_1_schema():
    """打印 @tool 自动生成的 schema，对比 Agent L04 手写的 TOOLS_SPEC。"""
    print("\n" + "═" * 64)
    print("实验①：@tool 自动生成的 schema（对比 Agent L04 手写）")
    print("═" * 64)

    print("\n以 calculator 为例，@tool 自动生成的 schema：")
    schema = calculator.args_schema.model_json_schema()
    print(json.dumps(schema, ensure_ascii=False, indent=2))

    print("""
对比 Agent L04 手写的 TOOLS_SPEC_GOOD（每个工具要写这样的 JSON）：
    {"type": "function", "function": {
        "name": "calculator",
        "description": "计算数学表达式...",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "数学表达式"}
        }, "required": ["expression"]}
    }}

👉 @tool 从这些自动生成：
   - name      ← 函数名 def calculator
   - description ← docstring 第一段
   - 参数类型    ← 类型注解 expression: str
   - required  ← 没默认值的自动进 required
   - 参数描述    ← docstring 的 Args 段

   你只写一份函数代码，schema 自动派生——消灭了 Agent L04 的三份副本。
   但注意：description（docstring）的质量仍决定模型能否选对工具（L04 的教训不变）。
""")


# ════════════════════════════════════════════════════════════
# 实验②：create_agent 一行建 Agent
# ════════════════════════════════════════════════════════════
def experiment_2_prebuilt_agent(llm):
    """用 create_agent 一行创建 Agent，对比 L06 手写的整张图。"""
    print("\n" + "═" * 64)
    print("实验②：create_agent 一行建 Agent（对比 L06 手写图）")
    print("═" * 64)

    # L06 手写（约 15 行）：
    #   builder = StateGraph(MessagesState)
    #   builder.add_node("agent", call_model)
    #   builder.add_node("tools", ToolNode(tools))
    #   builder.add_edge(START, "agent")
    #   builder.add_conditional_edges("agent", tools_condition)
    #   builder.add_edge("tools", "agent")
    #   graph = builder.compile()

    # ⭐ 框架版（1 行 + system_prompt）：
    agent = create_agent(
        llm,
        TOOLS,
        system_prompt="你是一个严谨的助手。优先使用工具获取精确信息，不要编造。",
    )
    print("\n✅ Agent 已创建（create_agent 内部就是 L06 那张图）")

    # 跑一个多步任务
    question = "现在是几点？'人工智能'有几个字？"
    print(f"\n问题：{question}")
    result = agent.invoke({"messages": [HumanMessage(content=question)]})

    print(f"\n消息轨迹（共 {len(result['messages'])} 条）：")
    for i, msg in enumerate(result["messages"]):
        role = type(msg).__name__
        tc = getattr(msg, "tool_calls", None)
        content = str(msg.content).replace("\n", " ")[:45]
        print(f"  [{i}] {role}: {content}")
        if tc:
            for call in tc:
                print(f"        ↳ 工具调用: {call['name']}({call['args']})")

    print(f"\n🤖 最终答案：{result['messages'][-1].content[:100]}")
    print("\n👉 对比 L06：create_agent 把 agent+tools+条件边+回路全预置了。")
    print("   但它就是 L06 那张图的封装——你懂了 L06 的原理，才知道它背后是什么。")


# ════════════════════════════════════════════════════════════
# 实验③：真实细节——LLM 用工具时会犯错（description 仍是灵魂）
# ════════════════════════════════════════════════════════════
def experiment_3_llm_mistakes(llm):
    """演示一个真实现象：模型可能用 2^10 算乘方（^ 在 Python 是异或）。

    这不是框架的 bug，是 LLM 对工具参数理解的局限——
    说明 description 的质量仍是关键（Agent L04 的教训在框架里同样适用）。
    """
    print("\n" + "═" * 64)
    print("实验③：真实细节——LLM 用工具时会犯错")
    print("═" * 64)

    agent = create_agent(llm, [calculator])

    question = "帮我算一下 2 的 10 次方是多少？"
    print(f"\n问题：{question}")
    print("（注意：模型可能传 '2^10' 给 calculator，但 ^ 在 Python 是异或，结果会是 8 而非 1024）\n")

    result = agent.invoke({"messages": [HumanMessage(content=question)]})

    # 找到工具调用，看模型传了什么表达式
    for msg in result["messages"]:
        tc = getattr(msg, "tool_calls", None)
        if tc:
            for call in tc:
                expr = call["args"].get("expression", "?")
                print(f"  模型传给 calculator 的表达式：{expr!r}")
                if "^" in expr:
                    print(f"  ⚠️ 模型用了 ^ —— 在 Python 里是异或！2^10 = {2^10}（不是 1024）")
                    print(f"     这说明模型对工具参数的理解有局限。")
                elif "**" in expr:
                    print(f"  ✅ 模型用了 ** —— 正确的 Python 乘方语法，2**10 = 1024")

    final = result["messages"][-1].content
    print(f"\n🤖 模型的最终答案：{final[:80]}")

    print("""
👉 关键认知：
   框架帮你把工具接上了（@tool + create_agent），
   但工具能不能被'正确使用'，仍取决于 description 的质量。
   我们在 calculator 的 docstring 里写了'用 ** 表示乘方'——
   如果没写，模型更容易犯错。这就是 Agent L04 的教训：description 是灵魂。
   框架换了写 description 的位置（JSON → docstring），没降低它的重要性。
""")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 07 — 框架级 Agent：Tools + prebuilt Agents")
    print("=" * 64)
    print("把 Agent L02+L04+L06 手写的工具定义和图组装，完全框架化。")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    experiment_1_schema()              # @tool 自动 schema
    experiment_2_prebuilt_agent(llm)   # create_agent
    experiment_3_llm_mistakes(llm)     # 真实细节

    print("=" * 64)
    print("✅ 框架级 Agent 小结：")
    print("   - @tool：从类型注解+docstring 自动生成 schema（消灭三份副本）")
    print("   - create_agent：一行建 Agent（L06 那张图的封装）")
    print("   - description 仍是灵魂（框架换了位置，没降重要性）")
    print("   - 何时预置/何时手写：标准 ReAct 用预置，自定义流程手写图")
    print("=" * 64)


if __name__ == "__main__":
    main()
