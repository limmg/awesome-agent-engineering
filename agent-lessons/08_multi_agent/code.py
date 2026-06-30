"""
L08 — 多智能体协作
==================
实现一个 3-Agent 流水线：规划者 + 执行者 + 审查者
    ① 规划者：把任务拆成步骤清单
    ② 执行者：按计划执行（调用工具）
    ③ 审查者：检查结果质量，可打回重做

运行：python agent-lessons/08_multi_agent/code.py
"""
from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from zhipuai import ZhipuAI

CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"
MAX_REWORK_ROUNDS = 2  # 审查不通过时，最多让执行者重做的次数


def create_client() -> ZhipuAI:
    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    return ZhipuAI(api_key=api_key)


# ════════════════════════════════════════════════════════════
# 执行者用的工具（复用前面的）
# ════════════════════════════════════════════════════════════
def get_weather(city: str) -> str:
    weather_map = {"北京": ("晴", 25), "上海": ("多云", 28), "广州": ("雨", 30), "深圳": ("阴", 29)}
    if city not in weather_map:
        return f"没有 {city} 的数据"
    cond, t = weather_map[city]
    return f"{city}：{cond}，{t}°C"


def calculator(expression: str) -> str:
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：非法字符"
        return str(eval(expression))
    except Exception as e:
        return f"计算错误：{e}"


TOOL_REGISTRY = {"get_weather": get_weather, "calculator": calculator}
TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "get_weather", "description": "查询城市天气。",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    }},
    {"type": "function", "function": {
        "name": "calculator", "description": "计算数学表达式。",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
    }},
]


def execute_function(name: str, args: dict) -> str:
    if name not in TOOL_REGISTRY:
        return f"错误：工具 '{name}' 不存在"
    try:
        return str(TOOL_REGISTRY[name](**args))
    except Exception as e:
        return f"工具失败：{e}"


# ════════════════════════════════════════════════════════════
# Agent 1：规划者（Planner）
# ════════════════════════════════════════════════════════════
PLANNER_PROMPT = """你是一个任务规划专家（规划者）。你的职责是把用户任务分解成清晰的执行步骤。

要求：
1. 输出 JSON：{"steps": ["步骤1", "步骤2", ...]}
2. 每个步骤具体、可执行
3. 不要执行任务，只规划
4. 只输出 JSON，不要其他内容"""


def planner(client: ZhipuAI, task: str) -> list[str]:
    """规划者：输出任务步骤清单。"""
    print(f"\n🧠 【规划者】接到任务：{task}")
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": f"任务：{task}"},
        ],
    )
    content = resp.choices[0].message.content.strip()
    # 提取 JSON
    json_match = re.search(r'\{[^{}]*"steps"[^{}]*\}', content, re.DOTALL)
    if json_match:
        content = json_match.group(0)
    try:
        steps = json.loads(content).get("steps", [])
    except json.JSONDecodeError:
        steps = [content]

    print(f"📋 规划者输出 {len(steps)} 步：")
    for i, s in enumerate(steps, 1):
        print(f"   {i}. {s}")
    return steps


# ════════════════════════════════════════════════════════════
# Agent 2：执行者（Executor）
# ════════════════════════════════════════════════════════════
EXECUTOR_PROMPT = """你是一个任务执行者。你的职责是按计划逐步执行任务，调用工具获取信息。

你会收到：原始任务、步骤清单、之前已完成步骤的结果。
请执行所有步骤，最后给出完整的执行结果总结。"""


def executor(client: ZhipuAI, task: str, steps: list[str]) -> str:
    """执行者：按计划执行任务，可调用工具。"""
    print(f"\n🏃 【执行者】开始按计划执行...")
    messages = [
        {"role": "system", "content": EXECUTOR_PROMPT},
        {"role": "user", "content": f"原始任务：{task}\n步骤计划：{json.dumps(steps, ensure_ascii=False)}\n请逐步执行所有步骤。"},
    ]

    for step in range(6):  # 最多6轮工具调用
        resp = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages, tools=TOOLS_SPEC, tool_choice="auto"
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                result = execute_function(name, args)
                print(f"   🔧 调用 {name}({args}) → {result}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            print(f"   ✅ 执行者总结：{msg.content[:80]}")
            return msg.content
    return "（执行者达到最大步数）"


# ════════════════════════════════════════════════════════════
# Agent 3：审查者（Reviewer）
# ════════════════════════════════════════════════════════════
REVIEWER_PROMPT = """你是一个严格的质量审查者。你的职责是检查执行者的结果是否正确、完整地完成了原始任务。

判断标准：
- 结果是否回答了原始任务的所有要求？
- 有没有遗漏或错误？

输出格式：
- 如果通过：输出 "通过：结果正确完整。"
- 如果不通过：输出 "不通过：[具体问题]。需要补充：[什么]。"
只输出判断结论，不要重复结果本身。"""


def reviewer(client: ZhipuAI, task: str, execution_result: str) -> tuple[bool, str]:
    """审查者：检查执行结果，返回（是否通过, 审查意见）。"""
    print(f"\n🔍 【审查者】检查结果质量...")
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": REVIEWER_PROMPT},
            {"role": "user", "content": f"原始任务：{task}\n执行结果：{execution_result}\n\n请审查这个结果是否正确完整。"},
        ],
    )
    verdict = resp.choices[0].message.content.strip()
    passed = "通过" in verdict and "不通过" not in verdict
    status = "✅ 通过" if passed else "❌ 不通过"
    print(f"   {status}：{verdict[:80]}")
    return passed, verdict


# ════════════════════════════════════════════════════════════
# 3-Agent 协作流水线
# ════════════════════════════════════════════════════════════
def run_multi_agent(client: ZhipuAI, task: str):
    """完整的 3-Agent 协作流程：规划 → 执行 → 审查（可循环重做）。"""
    print("\n" + "═" * 60)
    print(f"🎯 任务：{task}")
    print("═" * 60)

    # Agent 1：规划
    steps = planner(client, task)

    # Agent 2 → Agent 3 循环：执行 + 审查，审查不过就重做
    result = ""
    for round_num in range(1, MAX_REWORK_ROUNDS + 2):  # 至少执行1次，最多重做MAX次
        if round_num > 1:
            print(f"\n\n🔄 第 {round_num} 轮（审查不通过，重做）")
        # Agent 2：执行
        result = executor(client, task, steps)
        # Agent 3：审查
        passed, verdict = reviewer(client, task, result)
        if passed:
            print(f"\n🎉 审查通过！最终结果：\n{result}")
            return result
        # 不通过：把审查意见加入，重新执行
        if round_num <= MAX_REWORK_ROUNDS:
            task = f"{task}\n（上一轮审查意见：{verdict}，请改进）"

    print(f"\n⚠️ 达到最大重做次数 {MAX_REWORK_ROUNDS}，最终结果：\n{result}")
    return result


def main():
    print("=" * 60)
    print("L08 — 多智能体协作（规划者 + 执行者 + 审查者）")
    print("=" * 60)

    client = create_client()

    # 任务：需要规划、执行（多工具）、审查
    run_multi_agent(
        client,
        "帮我查北京和上海的天气，比较哪个更热，算出温差，给出穿衣建议。",
    )

    print("\n\n" + "=" * 60)
    print("完成！3个 Agent 各司其职：")
    print("  规划者：拆任务，不执行")
    print("  执行者：按计划调工具，不操心全局")
    print("  审查者：挑毛病把关，可打回重做")
    print("💡 多 Agent = 关注点分离。但代价是成本和复杂度翻倍。")
    print("=" * 60)


if __name__ == "__main__":
    main()
