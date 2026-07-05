"""
Lesson 02 — Swarm 与 Handoff：Agent 间状态交接
================================================
本课对比 L01 的 supervisor，讲另一种多智能体拓扑：Swarm（去中心化）。

核心问题：
    L01 supervisor 每个 worker 干完活都要【回中心汇报】，由中心再决定下一步。
    但很多场景（如客服：分诊→退款→售后）Agent 之间可以【直接交接】，
    不必每次都回中心——这就是 Swarm + Handoff。

三个部分：
  ① Swarm 客服系统：分诊→退款→售后，Agent 间直接 handoff（不回中心）
  ② 对比 supervisor vs swarm 的消息流（看清"经过中心"vs"直接交接"）
  ③ 对比两者的拓扑图（星型 vs 网状）

映射：agent-lessons/08_multi_agent（你手写的字符串拼接传信息）
对比：workflow-lessons/01_supervisor_pattern（L01 的中心化调度）

运行：python workflow-lessons/02_swarm_handoff/code.py
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

from dotenv import load_dotenv
from langchain_community.chat_models import ChatZhipuAI
from langchain.agents import create_agent
from langgraph_swarm import create_swarm, create_handoff_tool  # 本课主角：swarm
from langgraph_supervisor import create_supervisor             # L01 主角：用于对比

CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 第 1 步：构建 Swarm 客服系统（去中心化）
# ════════════════════════════════════════════════════════════
def build_swarm_system(llm):
    """构建 Swarm 客服系统。

    对比 L01 supervisor：
        supervisor：所有 worker 只跟 supervisor 通信，worker→supervisor→worker（经过中心）
        swarm：Agent 之间直接 handoff，triage→refund→after_sales（不经过中心）

    对比 Agent L08 手写：
        手写用 task = f"{task}\\n(审查意见：{verdict})" 字符串拼接传信息
        swarm 用 handoff 工具传递【控制权 + 完整对话上下文】，结构化、不丢信息
    """
    # ── Agent 1：分诊员（triage）—— 拿到用户请求，分类后转交 ──
    # 给它两个 handoff 工具：能转给 refund 或 after_sales
    triage = create_agent(
        llm,
        tools=[
            create_handoff_tool(agent_name="refund"),
            create_handoff_tool(agent_name="after_sales"),
        ],
        name="triage",
        system_prompt=(
            "你是客服分诊员。你的职责是【分类并转交】，不要自己解决问题：\n"
            "  - 退款相关问题 → 转给 refund\n"
            "  - 售后/到账确认问题 → 转给 after_sales\n"
            "必须调用转交工具，不要直接回答用户。"
        ),
    )

    # ── Agent 2：退款专员（refund）—— 处理完退款后转给售后 ──
    refund = create_agent(
        llm,
        tools=[create_handoff_tool(agent_name="after_sales")],  # 只能转给售后
        name="refund",
        system_prompt=(
            "你是退款专员。处理退款请求（模拟：确认订单号、执行退款）。"
            "退款完成后，【必须】转交给 after_sales 做到账确认。"
        ),
    )

    # ── Agent 3：售后专员（after_sales）—— 终点站，处理完直接回复 ──
    after_sales = create_agent(
        llm,
        tools=[create_handoff_tool(agent_name="triage")],  # 遇到新问题可转回分诊
        name="after_sales",
        system_prompt=(
            "你是售后专员。负责退款到账确认、售后咨询。"
            "处理完成后直接回复用户，结束本次服务。"
            "如果用户提出全新问题，转回 triage 重新分诊。"
        ),
    )

    # ── Swarm：没有中心调度 ──
    # 对比 L01 create_supervisor：那里有 model=llm + prompt 指挥
    # 这里 create_swarm 没有 model/prompt 参数——因为没有一个"调度中心 LLM"
    # 必须指定 default_active_agent：用户消息先到谁那里（因为没有 supervisor 接活）
    return create_swarm(
        agents=[triage, refund, after_sales],
        default_active_agent="triage",  # ⚠️ 必传：第一个接用户消息的 agent
    ).compile()


# ════════════════════════════════════════════════════════════
# 第 2 步：构建 Supervisor 客服系统（用于对比，结构相同但中心化）
# ════════════════════════════════════════════════════════════
def build_supervisor_system(llm):
    """构建同样三个 agent 的 supervisor 系统，用于和 swarm 对比。

    注意：这里 triage/refund/after_sales 不需要 handoff 工具——
    因为它们都只跟 supervisor 通信，由 supervisor 决定派给谁。
    """
    triage = create_agent(
        llm, tools=[], name="triage",
        system_prompt="你是客服分诊员，判断用户问题类型。",
    )
    refund = create_agent(
        llm, tools=[], name="refund",
        system_prompt="你是退款专员，处理退款。",
    )
    after_sales = create_agent(
        llm, tools=[], name="after_sales",
        system_prompt="你是售后专员，处理售后和到账确认。",
    )

    # supervisor 版：有中心调度
    return create_supervisor(
        agents=[triage, refund, after_sales],
        model=llm,
        prompt="你是调度中心。退款派 refund，售后派 after_sales，分类先 triage。",
        output_mode="full_history",
    ).compile()


# ════════════════════════════════════════════════════════════
# 辅助：打印消息流（标注每条消息来自哪个 agent）
# ════════════════════════════════════════════════════════════
def print_message_flow(label, messages):
    print(f"\n【{label} 消息流】")
    print("━" * 60)
    for i, m in enumerate(messages):
        name = getattr(m, "name", None) or ""
        content = str(getattr(m, "content", "")).replace("\n", " ")
        if len(content) > 80:
            content = content[:80] + "..."
        tag = f"[{name}]" if name else ""
        print(f"  {i}. {type(m).__name__} {tag}: {content}")
    print("━" * 60)


# ════════════════════════════════════════════════════════════
# 实验 1：Swarm 去中心交接（核心演示）
# ════════════════════════════════════════════════════════════
def part_1_swarm_handoff(swarm_graph):
    """演示 swarm 的去中心交接。

    观察消息流：triage → refund → after_sales，
    Agent 之间直接 handoff，【没有】任何"回到中心"的步骤。

    对比 Agent L08 手写：那里用 task = f"{task}\\n(审查意见：{verdict})" 字符串拼接，
    信息可能丢失、格式混乱；swarm 的 handoff 传递【完整对话上下文】，不丢信息。
    """
    print("\n" + "─" * 60)
    print("实验 1：Swarm 去中心交接（triage → refund → after_sales）")
    print("─" * 60)
    task = "我要退款订单 12345，退款后请帮我确认到账。"
    print(f"📋 用户请求：{task}")
    print("\n观察：Agent 之间直接交接，不经过任何中心节点。\n")

    result = swarm_graph.invoke({"messages": [{"role": "user", "content": task}]})
    print_message_flow("Swarm", result["messages"])
    print(f"\n✅ 最终回复：{result['messages'][-1].content}")

    print("\n💡 关键观察：消息流里【没有】'transfer_back_to_supervisor'，")
    print("   triage→refund→after_sales 全程直接交接。这就是「去中心化」。")


# ════════════════════════════════════════════════════════════
# 实验 2：对比 supervisor（看清"经过中心"的差别）
# ════════════════════════════════════════════════════════════
def part_2_compare_with_supervisor(swarm_graph, supervisor_graph):
    """同一个任务，分别跑 swarm 和 supervisor，对比消息流。

    核心差别（看清 LLM 调用次数）：
        swarm：triage→refund→after_sales，3 个 agent 各调 1 次（3 次 LLM）
        supervisor：每次交接都过 supervisor，3 个 agent + 多次 supervisor（5+ 次 LLM）
    """
    print("\n\n" + "─" * 60)
    print("实验 2：同一个任务，Swarm vs Supervisor 消息流对比")
    print("─" * 60)
    task = "帮我退款订单 998，退款后确认到账。"

    # Swarm 版
    print(f"\n📋 任务：{task}")
    print("\n--- 【Swarm 版】（去中心）---")
    r1 = swarm_graph.invoke({"messages": [{"role": "user", "content": task}]})
    print_message_flow("Swarm", r1["messages"])
    swarm_llm_calls = sum(1 for m in r1["messages"] if type(m).__name__ == "AIMessage")

    # Supervisor 版
    print("\n--- 【Supervisor 版】（中心化）---")
    r2 = supervisor_graph.invoke({"messages": [{"role": "user", "content": task}]})
    print_message_flow("Supervisor", r2["messages"])
    sup_llm_calls = sum(1 for m in r2["messages"] if type(m).__name__ == "AIMessage")

    print(f"\n📊 LLM 调用次数对比：")
    print(f"   Swarm:      {swarm_llm_calls} 次 AIMessage")
    print(f"   Supervisor: {sup_llm_calls} 次 AIMessage")
    print(f"   差值: {sup_llm_calls - swarm_llm_calls} 次（supervisor 多出的「回中心」开销）")


# ════════════════════════════════════════════════════════════
# 实验 3：拓扑对比（网状 vs 星型）
# ════════════════════════════════════════════════════════════
def part_3_topology_compare(swarm_graph, supervisor_graph):
    """打印两者的 Mermaid 图，直观对比网状 vs 星型拓扑。"""
    print("\n\n" + "─" * 60)
    print("实验 3：拓扑对比（Swarm 网状 vs Supervisor 星型）")
    print("─" * 60)

    print("\n【Swarm 拓扑（网状）】")
    print(swarm_graph.get_graph().draw_mermaid())

    print("\n【Supervisor 拓扑（星型）】")
    print(supervisor_graph.get_graph().draw_mermaid())

    print("━" * 60)
    print("拓扑解读：")
    print("  Swarm（网状）: agent 之间直接 handoff，无中心节点，全虚线（条件边）")
    print("  Supervisor（星型）: supervisor 居中，worker→supervisor→worker，实线+虚线")
    print()
    print("  什么时候用 Swarm？  流程相对固定、Agent 各自知道下一步转给谁（如客服）")
    print("  什么时候用 Supervisor？ 流程不可预测、需要中心动态决策（如研究/分析）")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 02 — Swarm 与 Handoff：Agent 间状态交接")
    print("=" * 64)
    print("对比 L01 supervisor，讲另一种拓扑：Swarm（去中心化）。")
    print("映射：agent-lessons/08_multi_agent（手写字符串拼接传信息）")
    print("对比：workflow-lessons/01_supervisor_pattern（中心化调度）")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    print("\n🔧 构建 Swarm 客服系统（triage + refund + after_sales，去中心）...")
    swarm_graph = build_swarm_system(llm)
    print("✅ Swarm 图已编译")

    print("🔧 构建 Supervisor 客服系统（同样 3 agent，但有中心调度，用于对比）...")
    supervisor_graph = build_supervisor_system(llm)
    print("✅ Supervisor 图已编译")

    part_1_swarm_handoff(swarm_graph)                  # Swarm 去中心交接
    part_2_compare_with_supervisor(swarm_graph, supervisor_graph)  # 对比消息流
    part_3_topology_compare(swarm_graph, supervisor_graph)         # 对比拓扑

    print("\n" + "=" * 64)
    print("✅ Swarm 与 Handoff 小结：")
    print("   - Swarm = 去中心：Agent 之间直接 handoff，不经过任何调度中心")
    print("   - handoff 本质是个工具（transfer_to_xxx），LLM 调用它=转交控制权")
    print("   - create_swarm 必传 default_active_agent（因为没有 supervisor 接活）")
    print("   - 对比 L01 supervisor：swarm 省 '回中心' 的 LLM 调用，更快更省")
    print("   - 对比手写 L08：字符串拼接 → 结构化的 handoff（传递完整上下文）")
    print("   - 代价：每个 agent 必须自己'知道何时转给谁'，prompt 设计要求更高")
    print("=" * 64)


if __name__ == "__main__":
    main()
