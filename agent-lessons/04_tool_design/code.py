"""
L04 — 多工具与工具设计
======================
配 6 个工具，做实验观察工具选择的难点：
    ① 6 个工具的工具箱（含字符串、列表、单位换算等）
    ② 实验：复杂任务的多工具配合
    ③ 实验：description 模糊 → 选错（对比好/差 description）
    ④ 实验：功能重叠工具的困扰

运行：python agent-lessons/04_tool_design/code.py
"""
from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from zhipuai import ZhipuAI

CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"


def create_client() -> ZhipuAI:
    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    return ZhipuAI(api_key=api_key)


# ════════════════════════════════════════════════════════════
# 工具函数实现
# ════════════════════════════════════════════════════════════


def get_weather(city: str, unit: str = "摄氏度") -> str:
    weather_map = {
        "北京": ("晴", 25), "上海": ("多云", 28), "广州": ("雨", 30),
        "深圳": ("阴", 29), "杭州": ("晴", 26),
    }
    if city not in weather_map:
        return f"抱歉，没有 {city} 的天气数据。支持：{list(weather_map.keys())}"
    cond, t = weather_map[city]
    if unit == "华氏度":
        t = t * 9 / 5 + 32
        return f"{city}：{cond}，{t:.0f}°F"
    return f"{city}：{cond}，{t}°C"


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


def string_reverse(text: str) -> str:
    return f"'{text}' 反转后是 '{text[::-1]}'"


def list_sort(numbers: list) -> str:
    """对数字列表升序排序。"""
    try:
        nums = [float(n) for n in numbers]
        nums_sorted = sorted(nums)
        return f"排序结果（升序）：{nums_sorted}"
    except Exception as e:
        return f"排序失败：{e}"


def unit_convert(value: float, from_unit: str, to_unit: str) -> str:
    """单位换算。支持：米↔千米，摄氏度↔华氏度。"""
    convert_map = {
        ("米", "千米"): lambda v: v / 1000,
        ("千米", "米"): lambda v: v * 1000,
        ("摄氏度", "华氏度"): lambda v: v * 9 / 5 + 32,
        ("华氏度", "摄氏度"): lambda v: (v - 32) * 5 / 9,
    }
    key = (from_unit, to_unit)
    if key not in convert_map:
        supported = [f"{f}→{t}" for f, t in convert_map]
        return f"不支持的换算：{from_unit}→{to_unit}。支持：{supported}"
    result = convert_map[key](value)
    return f"{value}{from_unit} = {result:.2f}{to_unit}"


# ──────────────────────────────────────────────────────────────
# 好的 description 版本（清晰具体）
# ──────────────────────────────────────────────────────────────
TOOL_REGISTRY = {
    "get_weather": get_weather,
    "calculator": calculator,
    "string_length": string_length,
    "string_reverse": string_reverse,
    "list_sort": list_sort,
    "unit_convert": unit_convert,
}

TOOLS_SPEC_GOOD = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "查询指定城市的实时天气。当用户问'XX天气''XX下雨吗''气温多少度'时使用。不支持查询非城市（如国家、星球）。",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名，如'北京'"},
            "unit": {"type": "string", "enum": ["摄氏度", "华氏度"], "description": "温度单位，默认摄氏度"},
        }, "required": ["city"]},
    }},
    {"type": "function", "function": {
        "name": "calculator",
        "description": "计算数学表达式（四则运算）。需要精确计算加减乘除时使用。expression 是数学表达式，如 '12*34' 或 '(1+2)*3'。注意：不能解方程、不能求导。",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '3 * (4 + 5)'"},
        }, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "string_length",
        "description": "计算字符串的字符数（长度）。当用户问'XX有几个字''XX多长''XX长度'时使用。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要计算长度的字符串"},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "string_reverse",
        "description": "把字符串反转（首尾倒过来）。当用户说'倒序''反转''逆序输出'时使用。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要反转的字符串"},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "list_sort",
        "description": "对一组数字进行升序排序（从小到大）。当用户说'排序''从小到大排''整理这组数字'时使用。",
        "parameters": {"type": "object", "properties": {
            "numbers": {"type": "array", "items": {"type": "number"}, "description": "要排序的数字列表，如 [3, 1, 4, 1, 5]"},
        }, "required": ["numbers"]},
    }},
    {"type": "function", "function": {
        "name": "unit_convert",
        "description": "单位换算。支持：米↔千米、摄氏度↔华氏度。当用户问'XX米等于多少千米''XX摄氏度等于多少华氏度'时使用。",
        "parameters": {"type": "object", "properties": {
            "value": {"type": "number", "description": "要换算的数值"},
            "from_unit": {"type": "string", "description": "原始单位，如'米'、'摄氏度'"},
            "to_unit": {"type": "string", "description": "目标单位，如'千米'、'华氏度'"},
        }, "required": ["value", "from_unit", "to_unit"]},
    }},
]

# ──────────────────────────────────────────────────────────────
# 差的 description 版本（模糊，故意制造选错）
# ──────────────────────────────────────────────────────────────
TOOLS_SPEC_BAD = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "查询功能。",  # 极其模糊
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"}}, "required": ["city"]},
    }},
    {"type": "function", "function": {
        "name": "calculator",
        "description": "处理数字。",  # 模糊
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string"}}, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "string_length",
        "description": "处理字符串。",  # 和 string_reverse 重叠！
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "string_reverse",
        "description": "处理字符串。",  # 和 string_length 重叠！
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "list_sort",
        "description": "处理数据。",  # 模糊
        "parameters": {"type": "object", "properties": {
            "numbers": {"type": "array", "items": {"type": "number"}}}, "required": ["numbers"]},
    }},
    {"type": "function", "function": {
        "name": "unit_convert",
        "description": "单位换算。支持米↔千米、摄氏度↔华氏度。当用户问'XX米等于多少千米'时使用。",  # 模糊
        "parameters": {"type": "object", "properties": {
            "value": {"type": "number"},
            "from_unit": {"type": "string"},
            "to_unit": {"type": "string"},
        }, "required": ["value", "from_unit", "to_unit"]},
    }},
]


# ──────────────────────────────────────────────────────────────
# 极限差的 description 版本（参数名也混淆）
# ──────────────────────────────────────────────────────────────
TOOLS_SPEC_BAD_EXTREME = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "获取数据。",
        "parameters": {"type": "object", "properties": {
            "p1": {"type": "string"}}, "required": ["p1"]},
    }},
    {"type": "function", "function": {
        "name": "calculator",
        "description": "计算。",
        "parameters": {"type": "object", "properties": {
            "p1": {"type": "string"}}, "required": ["p1"]},
    }},
    {"type": "function", "function": {
        "name": "string_length",
        "description": "操作文本。",
        "parameters": {"type": "object", "properties": {
            "p1": {"type": "string"}}, "required": ["p1"]},
    }},
    {"type": "function", "function": {
        "name": "string_reverse",
        "description": "操作文本。",
        "parameters": {"type": "object", "properties": {
            "p1": {"type": "string"}}, "required": ["p1"]},
    }},
    {"type": "function", "function": {
        "name": "list_sort",
        "description": "处理。",
        "parameters": {"type": "object", "properties": {
            "p1": {"type": "array", "items": {"type": "number"}}}, "required": ["p1"]},
    }},
    {"type": "function", "function": {
        "name": "unit_convert",
        "description": "转换。",
        "parameters": {"type": "object", "properties": {
            "p1": {"type": "number"},
            "p2": {"type": "string"},
            "p3": {"type": "string"},
        }, "required": ["p1", "p2", "p3"]},
    }},
]

# 极限坏版的参数映射：把 p1/p2/p3 映射回真实参数名
EXTREME_ARG_MAP = {
    "get_weather": {"p1": "city"},
    "calculator": {"p1": "expression"},
    "string_length": {"p1": "text"},
    "string_reverse": {"p1": "text"},
    "list_sort": {"p1": "numbers"},
    "unit_convert": {"p1": "value", "p2": "from_unit", "p3": "to_unit"},
}


def execute_function(name: str, arguments: dict, extreme: bool = False) -> str:
    if name not in TOOL_REGISTRY:
        return f"错误：工具 '{name}' 不存在"
    # 极限坏版：参数名是 p1/p2/p3，需要映射回真实参数名
    if extreme and name in EXTREME_ARG_MAP:
        mapped = {}
        for fake_key, real_key in EXTREME_ARG_MAP[name].items():
            if fake_key in arguments:
                mapped[real_key] = arguments[fake_key]
        arguments = mapped
    try:
        return str(TOOL_REGISTRY[name](**arguments))
    except Exception as e:
        return f"工具执行失败：{e}"


def run_agent(client: ZhipuAI, question: str, tools_spec: list, max_steps: int = 6, extreme: bool = False, model: str = None) -> str | None:
    """运行 Agent，用指定的 tools_spec（好版/差版）。extreme=True 时参数名需要映射。"""
    _model = model or CHAT_MODEL
    messages = [{"role": "user", "content": question}]
    used_tools = []  # 记录用过哪些工具，供分析

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=_model, messages=messages, tools=tools_spec, tool_choice="auto"
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                result = execute_function(name, args, extreme=extreme)
                used_tools.append(name)
                print(f"  第{step}步 调用 {name}({args}) → {result[:50]}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            print(f"  回答：{msg.content[:80]}")
            return msg.content
    return None


def main():
    print("=" * 60)
    print("L04 — 多工具与工具设计")
    print("=" * 60)
    client_strong = create_client()
    print(f"\n当前强模型：{CHAT_MODEL}（请确认你在用 glm-4 而非 flash）")

    # ════════════════════════════════════════════════════════════
    # 实验 1：glm-4 + 好 spec → 完美
    # ════════════════════════════════════════════════════════════
    print("\n" + "═" * 60)
    print("实验 1：强模型 + 好 description（基线，肯定全对）")
    print("═" * 60)
    run_agent(
        client_strong,
        "帮我把 5 千米换算成米，然后把结果和 1234 相加，最后算 '人工智能' 有几个字。",
        TOOLS_SPEC_GOOD,
    )

    # ════════════════════════════════════════════════════════════
    # 实验 2：glm-4 + 极限坏 spec → glm-4 可能还能猜对
    # ════════════════════════════════════════════════════════════
    print("\n\n" + "═" * 60)
    print("实验 2：强模型 + 极限坏 description（参数名也混淆）")
    print("═" * 60)
    print("（glm-4 太强了，即使参数都叫 p1/p2/p3，它还是能通过参数类型和数量推理出来）\n")
    run_agent(
        client_strong,
        "帮我把 5 千米换算成米，然后把结果和 1234 相加，最后算 '人工智能' 有几个字。",
        TOOLS_SPEC_BAD_EXTREME,
        extreme=True,
    )

    # ════════════════════════════════════════════════════════════
    # 实验 3：glm-4-flash + 极限坏 spec → 对比弱模型
    # ════════════════════════════════════════════════════════════
    print("\n\n" + "═" * 60)
    print("实验 3：弱模型 glm-4-flash + 极限坏 description（关键对比！）")
    print("═" * 60)
    print("（同样的问题和工具，但换成 glm-4-flash——观察弱模型会不会翻车）\n")
    run_agent(
        client_strong,
        "帮我把 5 千米换算成米，然后把结果和 1234 相加，最后算 '人工智能' 有几个字。",
        TOOLS_SPEC_BAD_EXTREME,
        extreme=True,
        model="glm-4-flash",
    )

    # ════════════════════════════════════════════════════════════
    # 实验 4：功能重叠 + 弱模型 → 选错概率最高
    # ════════════════════════════════════════════════════════════
    print("\n\n" + "═" * 60)
    print("实验 4：弱模型 + 功能重叠（list_sort vs calculator 无法区分）")
    print("═" * 60)
    print("（所有工具描述都极模糊，试试 glm-4-flash 能不能选对 list_sort）\n")
    run_agent(
        client_strong,
        "帮我把 3,1,4,1,5,9,2,6 这组数字排序。",
        TOOLS_SPEC_BAD_EXTREME,
        extreme=True,
        model="glm-4-flash",
    )

    print("\n" + "═" * 60)
    print("对比要点：")
    print("  实验 1（强模型+好 spec）：✓ 完美")
    print("  实验 2（强模型+极限坏）：glm-4 靠参数类型/数量仍可能猜对")
    print("  实验 3（弱模型+极限坏）：弱模型更容易翻车")
    print("  实验 4（弱模型+功能重叠）：模糊工具间的选择，最容易被混淆")
    print("=" * 60)


if __name__ == "__main__":
    main()
