"""
Lesson 01 — Supervisor 主从模式：动态路由调度
================================================
本课是多智能体编排的第一课。核心问题：

    你在 Agent L08 手写过 3-Agent 流水线（规划者→执行者→审查者），
    但那是「写死的 for 循环顺序」——supervisor 解决的是「运行时动态路由」。

三个部分：
  ① 对比手写 L08：写死的 planner→executor→reviewer 顺序
  ② 用 create_supervisor 重写：supervisor 动态决定派给谁
  ③ 看清拓扑：打印 Mermaid 图 + 完整消息流（看清动态路由过程）

映射：agent-lessons/08_multi_agent（手写 3-Agent 流水线）

运行：python workflow-lessons/01_supervisor_pattern/code.py
"""
# 消除 langchain-community 的 sunset 警告（不影响使用）
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")

import os

from dotenv import load_dotenv
from langchain_community.chat_models import ChatZhipuAI
from langchain.agents import create_agent          # 框架课 L07 用过的"一行建 Agent"
from langchain_core.tools import tool              # @tool 装饰器
from langgraph_supervisor import create_supervisor # 本课主角：supervisor 编排

CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 工具：复用 Agent L08 的 get_weather / calculator（让 worker 能干活）
# ════════════════════════════════════════════════════════════
@tool
def get_weather(city: str) -> str:
    """查询指定城市的天气情况，返回天气状况和温度。"""
    weather_map = {"北京": ("晴", 25), "上海": ("多云", 28), "广州": ("雨", 30), "深圳": ("阴", 29)}
    if city not in weather_map:
        return f"没有 {city} 的数据"
    cond, t = weather_map[city]
    return f"{city}：{cond}，{t}°C"


@tool
def calculator(expression: str) -> str:
    """计算数学表达式（支持加减乘除），返回计算结果。"""
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：非法字符"
        return str(eval(expression))
    except Exception as e:
        return f"计算错误：{e}"


# ════════════════════════════════════════════════════════════
# 第 1 步：构建 supervisor 系统（3 个 worker + 1 个调度中心）
# ════════════════════════════════════════════════════════════
def build_supervisor_system(llm):
    """构建 supervisor 多智能体系统。

    对比 Agent L08 手写版：
        手写：planner() → executor() → reviewer()  写死的函数调用顺序
        框架：supervisor（LLM 调度）+ 3 个 worker（create_agent）
              supervisor 在【运行时】根据任务内容决定派给哪个 worker
              而且可以反复派、跳过、回来——不是固定流水线
    """
    # ── worker 1：研究员（负责查资料/查天气/算数，自带工具）──
    researcher = create_agent(
        llm,
        tools=[get_weather, calculator],   # worker 自己带工具
        name="researcher",                 # ⚠️ name 必须传！否则 supervisor 报错
        system_prompt=(
            "你是研究员，负责使用工具收集事实信息（查天气、做计算）。"
            "拿到任务后调用合适的工具获取数据，简洁汇报结果。"
        ),
    )

    # ── worker 2：分析师（负责分析推理，不带工具，纯脑力）──
    analyst = create_agent(
        llm,
        tools=[],                          # 纯推理，不需要工具
        name="analyst",
        system_prompt=(
            "你是数据分析师，负责对研究员收集的数据进行对比、分析、得出结论。"
            "例如比较两个城市的温差、判断哪个更适合某项活动。"
        ),
    )

    # ── worker 3：撰写者（负责把结论整理成文字）──
    writer = create_agent(
        llm,
        tools=[],
        name="writer",
        system_prompt=(
            "你是文案撰写者，负责把分析结论整理成一段通顺、完整的最终回答给用户。"
            "回答要包含完整信息，语气自然。"
        ),
    )

    # ── supervisor：调度中心（它本身也是个 LLM Agent）──
    #    对比手写 L08：那里没有"调度者"角色，顺序是写死的
    #    这里 supervisor 会拿到 3 个 handoff 工具（自动生成），
    #    运行时根据任务内容决定：先派谁、再派谁、要不要跳过某步
    supervisor = create_supervisor(
        agents=[researcher, analyst, writer],
        model=llm,
        prompt=(
            "你是任务调度中心。根据用户任务和当前进度，决定把任务派给哪个专家：\n"
            "  - researcher：需要查天气、做计算等收集事实的工作\n"
            "  - analyst：需要对已有数据做对比分析\n"
            "  - writer：需要把结论整理成最终回答\n"
            "你可以依次调用多个专家，根据上一步结果决定下一步派给谁。"
        ),
        output_mode="full_history",  # 保留完整消息历史（便于看清路由过程）
    )
    return supervisor.compile()


# ════════════════════════════════════════════════════════════
# 第 2 步：演示——同一个任务，supervisor 动态调度
# ════════════════════════════════════════════════════════════
def part_1_dynamic_routing(graph):
    """演示 supervisor 的动态路由。

    给一个复合任务（查天气 + 分析 + 整理），
    观察 supervisor 如何【动态】决定：先派 researcher 查数据，
    再派 analyst 分析，最后派 writer 整理。

    对比 Agent L08：那里是 planner()→executor()→reviewer() 写死的，
    即使任务不需要某一步，也会执行。
    """
    print("\n" + "─" * 60)
    print("实验 1：supervisor 动态调度一个复合任务")
    print("─" * 60)
    task = "帮我查北京和上海的天气，比较哪个更热，给出穿衣建议。"
    print(f"📋 任务：{task}")
    print("\n观察 supervisor 如何依次派给 researcher → analyst → writer：\n")

    result = graph.invoke({"messages": [{"role": "user", "content": task}]})

    # 打印完整消息流——这是 supervisor 动态路由的"证据"
    print("【完整消息流（看清动态路由过程）】")
    print("━" * 60)
    for msg in result["messages"]:
        msg_type = type(msg).__name__
        content = str(getattr(msg, "content", "")).replace("\n", " ")
        if len(content) > 100:
            content = content[:100] + "..."
        # 标注每条消息来自哪个 agent
        name = getattr(msg, "name", None) or ""
        tag = f"[{name}] " if name else ""
        print(f"  {tag}{msg_type}: {content}")
    print("━" * 60)
    print(f"\n✅ 最终回答：{result['messages'][-1].content}")


# ════════════════════════════════════════════════════════════
# 第 3 步：演示——简单任务只派一个 worker（体现"动态"价值）
# ════════════════════════════════════════════════════════════
def part_2_skip_unnecessary(graph):
    """演示 supervisor 会跳过不需要的 worker。

    给一个纯计算任务——supervisor 应该只派 researcher，
    不需要 analyst 和 writer（因为没有复杂数据要分析，也不长）。

    这正是手写 L08 做不到的：手写版不管任务大小，
    planner→executor→reviewer 全部走一遍。
    """
    print("\n\n" + "─" * 60)
    print("实验 2：简单任务，supervisor 只派必要的 worker")
    print("─" * 60)
    task = "算一下 12 乘以 8 等于多少"
    print(f"📋 任务：{task}")
    print("（这种简单任务，supervisor 应该只派 researcher，不走 analyst/writer）\n")

    result = graph.invoke({"messages": [{"role": "user", "content": task}]})

    print("【消息流】")
    print("━" * 60)
    for msg in result["messages"]:
        msg_type = type(msg).__name__
        content = str(getattr(msg, "content", "")).replace("\n", " ")
        if len(content) > 100:
            content = content[:100] + "..."
        name = getattr(msg, "name", None) or ""
        tag = f"[{name}] " if name else ""
        print(f"  {tag}{msg_type}: {content}")
    print("━" * 60)
    print(f"\n👉 对比手写 L08：写死的流水线不管任务大小都得走全套；")
    print("   supervisor 能根据任务复杂度【按需调度】，省 token、省时间。")


# ════════════════════════════════════════════════════════════
# 第 4 步：可视化 supervisor 的星型拓扑
# ════════════════════════════════════════════════════════════
def part_3_topology(graph):
    """打印 Mermaid 图——看清 supervisor 的星型拓扑。

    这是 supervisor 模式的视觉特征：
        supervisor 居中，所有 worker 围着它
        supervisor → worker 是虚线（条件边，动态决定派给谁）
        worker → supervisor 是实线（固定边，干完活必回中心汇报）
    """
    print("\n\n" + "─" * 60)
    print("实验 3：supervisor 的星型拓扑（Mermaid 图）")
    print("─" * 60)
    mermaid = graph.get_graph().draw_mermaid()
    print(mermaid)
    print("━" * 60)
    print("拓扑解读：")
    print("  - supervisor 居中 → 星型（hub-and-spoke）拓扑")
    print("  - 虚线(supervisor --> worker) = 条件边：运行时决定派给谁")
    print("  - 实线(worker --> supervisor) = 固定边：worker 干完必回中心")
    print("  - 对比手写 L08：那里没有图，是 planner→executor→reviewer 一条直线")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 01 — Supervisor 主从模式：动态路由调度")
    print("=" * 64)
    print("把 Agent L08 写死的 3-Agent 流水线，改成 supervisor 动态路由。")
    print("映射：agent-lessons/08_multi_agent")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    # 构建 supervisor 系统
    print("\n🔧 构建 supervisor 系统（1 调度中心 + 3 专家 worker）...")
    graph = build_supervisor_system(llm)
    print("✅ 图已编译")

    part_1_dynamic_routing(graph)   # 复合任务：动态派给 3 个 worker
    part_2_skip_unnecessary(graph)  # 简单任务：只派必要的 worker
    part_3_topology(graph)          # 看清星型拓扑

    print("\n" + "=" * 64)
    print("✅ Supervisor 主从模式小结：")
    print("   - supervisor 本身是个 LLM，运行时【动态决定】派给哪个 worker")
    print("   - worker 用 create_agent 创建（⚠️ 必须传 name= 参数）")
    print("   - create_supervisor 自动给 supervisor 生成 handoff 工具")
    print("   - 星型拓扑：worker 只跟 supervisor 通信，不互相通信")
    print("   - 对比手写 L08：写死的 for 循环 → 运行时动态路由")
    print("   - 代价：每次派发都过一遍 supervisor（多一次 LLM 调用，更贵）")
    print("=" * 64)


if __name__ == "__main__":
    main()
