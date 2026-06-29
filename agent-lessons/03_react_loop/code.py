"""
L03 — ReAct：思考-行动-观察循环（面试核心）
=============================================
完全手写一个最小 ReAct loop，不用任何框架。
结合 function calling（执行工具）+ ReAct prompt（显式思考），让 Agent 的推理过程完全可见。

运行：python agent-lessons/03_react_loop/code.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from dotenv import load_dotenv
from zhipuai import ZhipuAI

CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"
MAX_STEPS = 5  # ReAct 循环最大步数，防止死循环


def create_client() -> ZhipuAI:
    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    return ZhipuAI(api_key=api_key)


# ════════════════════════════════════════════════════════════
# 工具定义（复用 L02 的思路）
# ════════════════════════════════════════════════════════════


def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calculator(expression: str) -> str:
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：表达式包含非法字符"
        return str(eval(expression))
    except ZeroDivisionError:
        return "错误：除数不能为 0"
    except Exception as e:
        return f"计算错误：{e}"


def string_length(text: str) -> str:
    return f"'{text}' 的长度是 {len(text)} 个字符"


TOOL_REGISTRY = {
    "get_current_time": get_current_time,
    "calculator": calculator,
    "string_length": string_length,
}

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前日期和时间。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式。expression 如 '12 * 34'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "string_length",
            "description": "计算字符串的字符数。text 是要计算的字符串。",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "字符串"}},
                "required": ["text"],
            },
        },
    },
]


def execute_function(name: str, arguments: dict) -> str:
    if name not in TOOL_REGISTRY:
        return f"错误：工具 '{name}' 不存在"
    try:
        return str(TOOL_REGISTRY[name](**arguments))
    except Exception as e:
        return f"工具执行失败：{e}"


# ════════════════════════════════════════════════════════════
# ReAct 的灵魂：让模型显式思考的 system prompt
# ════════════════════════════════════════════════════════════
# 关键设计：用 function calling 执行工具，但同时要求模型在 content 里
# 输出它的 Thought（思考过程），让推理可见。
REACT_SYSTEM_PROMPT = """你是一个会使用工具的智能助手。面对用户的问题，请严格按以下方式工作：

每一步，你都要先在回答里写出你的【思考】，然后再决定是否调用工具：
- 用"💭 Thought:" 开头，写明你这一步的推理：我为什么要这么做、下一步打算干什么。
- 如果你需要调用工具来获取信息，在 Thought 之后正常调用工具。
- 如果你已经收集到足够信息可以回答用户了，用"✅ Final Answer:" 开头给出最终答案。

示例：
用户：现在几点？距离今天 18:00 还有几分钟？
💭 Thought: 用户问了两个问题。首先我需要知道当前时间，调用 get_current_time。
（调用 get_current_time）
观察：当前是 14:30
💭 Thought: 拿到现在时间 14:30，需要算 18:00 - 14:30 = 3.5 小时 = 210 分钟，调用 calculator。
（调用 calculator，expression="18*60 - 14*60 - 30"）
观察：210
✅ Final Answer: 现在是 14:30，距离 18:00 还有 210 分钟。

记住：每一步都要先写 Thought 再行动，让推理过程清晰可见。"""


# ════════════════════════════════════════════════════════════
# ReAct 循环（本课核心：手写，不用框架）
# ════════════════════════════════════════════════════════════
def run_react_agent(client: ZhipuAI, user_question: str, max_steps: int = MAX_STEPS):
    """手写的 ReAct 循环。

    和 L02 的 Agent 循环结构类似，但关键区别是：
    - 用 ReAct system prompt 让模型显式输出 Thought
    - 打印每一步的思考过程，让推理可见
    - 检测 Final Answer 判断是否完成
    """
    messages = [
        {"role": "system", "content": REACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_question},
    ]

    for step in range(1, max_steps + 1):
        print(f"\n{'━' * 50}")
        print(f"🔄 ReAct 第 {step} 轮")

        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            tools=TOOLS_SPEC,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        # ① 打印模型的 Thought（content 里就是它的思考过程）
        # 这是 ReAct 的核心价值：推理可见
        if msg.content:
            # 如果是 Final Answer，直接结束
            if "Final Answer" in msg.content or "✅" in msg.content:
                print(f"💬 {msg.content}")
                print(f"\n{'━' * 50}")
                print("✅ Agent 给出最终答案，循环结束。")
                return msg.content
            else:
                print(f"💭 Thought: {msg.content}")

        # ② 如果模型调用了工具，执行并把结果喂回去
        if msg.tool_calls:
            messages.append(msg.model_dump())
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                print(f"🔧 Action: 调用 {func_name}({func_args})")
                result = execute_function(func_name, func_args)
                print(f"👁️ Observation: {result}")

                messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result}
                )
        else:
            # 模型既没给 Final Answer 也没调用工具——可能直接回答了
            if msg.content:
                print(f"\n{'━' * 50}")
                print("✅ Agent 结束。")
                return msg.content

    print(f"\n⚠️ 达到最大步数 {max_steps}，Agent 被迫停止（防止死循环）。")
    return None


# ════════════════════════════════════════════════════════════
# 对比实验：原生 function calling（L02 风格，不带 Thought）
# ════════════════════════════════════════════════════════════
def run_plain_agent(client: ZhipuAI, user_question: str, max_steps: int = MAX_STEPS):
    """不带 ReAct prompt 的原生 function calling Agent（作为对比）。"""
    messages = [{"role": "user", "content": user_question}]
    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages, tools=TOOLS_SPEC, tool_choice="auto"
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                result = execute_function(name, args)
                print(f"  调用 {name}({args}) → {result}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            print(f"  回答：{msg.content[:80]}...")
            return msg.content
    return None


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("L03 — ReAct：思考-行动-观察循环（面试核心）")
    print("=" * 60)

    client = create_client()

    # 实验 1：用 ReAct 处理多步任务，看完整推理链
    print("\n\n" + "═" * 60)
    print("实验 1：ReAct Agent 的完整推理链")
    print("═" * 60)
    run_react_agent(
        client,
        "现在是几点？'人工智能'这四个字有几个字？把这两个数字相乘等于多少？",
    )

    # 实验 2：对比原生 function calling（没有 Thought）
    print("\n\n\n" + "═" * 60)
    print("实验 2：对比原生 function calling（没有 Thought）")
    print("═" * 60)
    print("（同样的任务，但不用 ReAct prompt——你看不到模型的思考过程）")
    run_plain_agent(
        client,
        "现在是几点？'人工智能'这四个字有几个字？把这两个数字相乘等于多少？",
    )

    print("\n\n" + "═" * 60)
    print("对比要点：")
    print("  ReAct：你能看到每步的 Thought（为什么这么做），推理可追溯。")
    print("  原生：只看到调了什么工具，不知道模型为什么这么决策。")
    print("=" * 60)
    print("\n💡 面试要点：ReAct = Reasoning + Acting，核心是让模型显式思考。")
    print("   手写过 ReAct loop 是 Agent 岗位的核心考点。")


if __name__ == "__main__":
    main()
