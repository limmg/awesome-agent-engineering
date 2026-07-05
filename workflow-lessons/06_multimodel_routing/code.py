"""
Lesson 06 — 多模型路由与网络拓扑（LangGraph 段收官）
=====================================================
本课做两件事，作为 LangGraph 主干段（L01-L06）的收官：

  ① 四种网络拓扑总览：把前 5 课学过的拓扑做系统对比（星型/环型/网状/层级）
  ② 多模型路由：supervisor 用 glm-4（贵但聪明，做决策），worker 用 glm-4-flash（免费快，做执行）

核心问题：
    前 5 课所有 Agent 都用同一个模型（glm-4）。
    但真实项目里：决策（调度/路由）需要聪明的 glm-4，执行（查资料/写文案）用 glm-4-flash 就够。
    多模型路由能在【不损失质量】的前提下大幅降本。

三个部分：
  ① 四种拓扑总览（ASCII 图 + 适用场景对比）
  ② 多模型路由：glm-4 supervisor + glm-4-flash worker
  ③ 层级拓扑：两层 supervisor（顶层决策 + 底层执行），综合 L01+L03

映射：agent-lessons/08_multi_agent（全程单一模型，无路由概念）
收官：前 5 课拓扑（L01 星型/L02 网状/L03 子图/L04 并行/L05 通信）系统总览
运行：python workflow-lessons/06_multimodel_routing/code.py
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
from langgraph_supervisor import create_supervisor

SMART_MODEL = "glm-4"        # 决策用：贵但聪明
FAST_MODEL = "glm-4-flash"   # 执行用：免费快


# ════════════════════════════════════════════════════════════
# 实验 1：四种网络拓扑总览（前 5 课的系统回顾）
# ════════════════════════════════════════════════════════════
def part_1_topology_overview():
    """打印四种拓扑的 ASCII 图和对比表。

    这是前 5 课的系统回顾——把 L01-L05 学的拓扑归类到四种经典网络拓扑里。
    """
    print("\n" + "─" * 60)
    print("实验 1：四种网络拓扑总览（前 5 课回顾）")
    print("─" * 60)

    print("""
① 星型拓扑（Star / Hub-and-Spoke）—— L01 Supervisor
   ┌──────────┐
   │supervisor│
   └──┬─┬─┬───┘
      │ │ │
   ┌──┘ │ └──┐
   ▼    ▼    ▼
 worker worker worker
   特点：中心调度，worker 只跟中心通信
   适合：流程不可预测，需中心动态决策

② 网状拓扑（Mesh）—— L02 Swarm
   ┌────────┐
   │ agent A │──┐
   └────┬───┘  │
        │  ┌───▼────┐
        └──│ agent B │
           └───┬────┘
               │
           ┌───▼────┐
           │ agent C │
           └────────┘
   特点：Agent 间直接 handoff，无中心
   适合：流程相对固定，Agent 各知下一步

③ 层级拓扑（Hierarchy）—— L03 子图 + L01 supervisor
       ┌──────────┐
       │ 顶层supv │
       └──┬───┬───┘
          │   │
     ┌────▼┐ ┌▼────┐
     │子图1│ │子图2│   （每个子图内部又有自己的拓扑）
     └─────┘ └─────┘
   特点：多层调度，大系统分而治之
   适合：Agent 数量多，需分组管理

④ 流水线拓扑（Pipeline / 环型）—— 手写 L08 + map-reduce
   START → A → B → C → END
   （或并行：fan-out → reduce）
   特点：固定顺序或并行，无动态路由
   适合：流程确定，步骤明确
""")

    print("【四种拓扑对比】")
    print("┌────────┬──────────┬────────────┬──────────────────┐")
    print("│ 拓扑    │ 本课对应  │ 通信方式    │ 典型场景          │")
    print("├────────┼──────────┼────────────┼──────────────────┤")
    print("│ 星型    │ L01      │ 经中心中转  │ 不可预测流程      │")
    print("│ 网状    │ L02      │ 直接 handoff│ 固定流程/客服     │")
    print("│ 层级    │ L01+L03  │ 层层下发    │ 大系统/多团队     │")
    print("│ 流水线  │ L04/L08  │ 顺序/并行   │ 确定性流程        │")
    print("└────────┴──────────┴────────────┴──────────────────┘")
    print("\n💡 真实系统常是【混合拓扑】：顶层层级，中层星型，底层流水线。")


# ════════════════════════════════════════════════════════════
# 实验 2：多模型路由（降本核心）
# ════════════════════════════════════════════════════════════
def part_2_multimodel_routing():
    """演示多模型路由：supervisor 用 glm-4，worker 用 glm-4-flash。

    对比前 5 课：所有 Agent 都用 glm-4（贵）。
    本实验：只有 supervisor 用 glm-4（决策质量高），worker 全用 glm-4-flash（免费）。
    决策质量不变（supervisor 够聪明），但执行成本降到 0。
    """
    print("\n\n" + "─" * 60)
    print("实验 2：多模型路由（glm-4 决策 + glm-4-flash 执行）")
    print("─" * 60)

    api_key = os.getenv("ZHIPUAI_API_KEY")
    # ⭐ 两个 LLM 实例：不同 model
    smart_llm = ChatZhipuAI(model=SMART_MODEL, api_key=api_key)   # 决策用
    fast_llm = ChatZhipuAI(model=FAST_MODEL, api_key=api_key)     # 执行用

    print(f"🧠 supervisor 用 {SMART_MODEL}（决策：判断派给谁、汇总结果）")
    print(f"⚡ worker 用 {FAST_MODEL}（执行：查资料、分析——免费！）")

    # worker 用 fast_llm（免费）
    researcher = create_agent(
        fast_llm, tools=[], name="researcher",
        system_prompt="你是研究员，简要回答问题（30字内）。",
    )
    analyst = create_agent(
        fast_llm, tools=[], name="analyst",
        system_prompt="你是分析师，简要分析（30字内）。",
    )

    # supervisor 用 smart_llm（决策需要聪明）
    supervisor = create_supervisor(
        agents=[researcher, analyst],
        model=smart_llm,  # ⭐ 只有 supervisor 用贵的
        prompt="你是调度中心。研究问题派 researcher，分析问题派 analyst。",
    )
    graph = supervisor.compile()

    task = "简要说明什么是RAG技术，并分析它的一个优点"
    print(f"\n📋 任务：{task}\n")

    result = graph.invoke({"messages": [{"role": "user", "content": task}]})

    print("【消息流（注意每个 agent 用什么模型）】")
    print("━" * 60)
    for m in result["messages"]:
        name = getattr(m, "name", None) or ""
        content = str(getattr(m, "content", "")).replace("\n", " ")
        if len(content) > 70:
            content = content[:70] + "..."
        tag = f"[{name}]" if name else ""
        # 标注模型
        if name == "supervisor":
            model_tag = f"({SMART_MODEL})"
        elif name:
            model_tag = f"({FAST_MODEL})"
        else:
            model_tag = ""
        print(f"  {tag}{model_tag}: {content}")
    print("━" * 60)
    print(f"\n✅ 最终回答：{result['messages'][-1].content[:100]}")

    print(f"\n💡 降本逻辑：")
    print(f"   - supervisor（{SMART_MODEL}）只在路由决策时调用，次数少")
    print(f"   - worker（{FAST_MODEL} 免费版）做大部分执行工作")
    print(f"   - 决策质量有保障（supervisor 够聪明），执行成本≈0")


# ════════════════════════════════════════════════════════════
# 实验 3：层级拓扑（L01 supervisor + L03 子图 综合）
# ════════════════════════════════════════════════════════════
def part_3_hierarchy():
    """演示层级拓扑：顶层 supervisor 调度，下层各 worker 用不同模型。

    这是 L01（supervisor）+ L06（多模型）的综合。
    架构：
        顶层 supervisor（glm-4）：决定派给"研究组"还是"写作组"
        研究组：researcher（glm-4-flash 快速查）
        写作组：writer（glm-4 写得更好——写作要质量）

    注意：不同 worker 也可以用不同模型！
    """
    print("\n\n" + "─" * 60)
    print("实验 3：层级拓扑 + 差异化模型（综合 L01+L03+L06）")
    print("─" * 60)

    api_key = os.getenv("ZHIPUAI_API_KEY")
    smart_llm = ChatZhipuAI(model=SMART_MODEL, api_key=api_key)
    fast_llm = ChatZhipuAI(model=FAST_MODEL, api_key=api_key)

    print("🏗️ 架构：")
    print(f"        顶层 supervisor（{SMART_MODEL} 决策）")
    print(f"         ├── researcher（{FAST_MODEL} 快速查资料）")
    print(f"         └── writer（{SMART_MODEL} 写作要质量）")

    # researcher 用 fast（查资料要快不要精致）
    researcher = create_agent(
        fast_llm, tools=[], name="researcher",
        system_prompt="你是研究员，用2-3句话回答问题。",
    )
    # writer 用 smart（写作需要质量）
    writer = create_agent(
        smart_llm, tools=[], name="writer",
        system_prompt="你是文案专家，把信息整理成优美的段落。",
    )

    # 顶层 supervisor 用 smart（决策 + 最终汇总都要质量）
    supervisor = create_supervisor(
        agents=[researcher, writer],
        model=smart_llm,
        prompt=(
            "你是总调度。需要查资料的派 researcher，"
            "需要整理成文的派 writer。可以依次调用多个。"
        ),
        output_mode="full_history",
    )
    graph = supervisor.compile()

    task = "查一下RAG技术是什么，然后整理成一段优美的介绍"
    print(f"\n📋 任务：{task}\n")

    result = graph.invoke({"messages": [{"role": "user", "content": task}]})

    print("【消息流（注意模型差异化）】")
    print("━" * 60)
    for m in result["messages"]:
        name = getattr(m, "name", None) or ""
        content = str(getattr(m, "content", "")).replace("\n", " ")
        if len(content) > 70:
            content = content[:70] + "..."
        tag = f"[{name}]" if name else ""
        # 差异化标注模型
        if name in ("supervisor", "writer"):
            model_tag = f"({SMART_MODEL})"
        elif name == "researcher":
            model_tag = f"({FAST_MODEL})"
        else:
            model_tag = ""
        print(f"  {tag}{model_tag}: {content}")
    print("━" * 60)

    print(f"\n✅ 最终回答：\n{result['messages'][-1].content[:200]}")

    print(f"\n💡 差异化模型的价值：")
    print(f"   - 不是所有 worker 都用同一个模型")
    print(f"   - researcher 用 fast（查资料，速度优先）")
    print(f"   - writer 用 smart（写文案，质量优先）")
    print(f"   - 按任务特点选模型 = 质量和成本的平衡")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 06 — 多模型路由与网络拓扑（LangGraph 段收官）")
    print("=" * 64)
    print("前 5 课拓扑总览 + 多模型路由降本。")
    print("映射：agent-lessons/08_multi_agent（全程单一模型）")
    print("收官：L01-L06 LangGraph 主干段完成")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")

    part_1_topology_overview()   # 四种拓扑总览
    part_2_multimodel_routing()  # 多模型路由
    part_3_hierarchy()           # 层级拓扑 + 差异化模型

    print("\n" + "=" * 64)
    print("✅ 多模型路由与拓扑小结（LangGraph 段收官）：")
    print("   - 四种拓扑：星型(L01)/网状(L02)/层级(L01+L03)/流水线(L04)")
    print("   - 多模型路由：supervisor 用 glm-4 决策，worker 用 glm-4-flash 执行")
    print("   - 差异化模型：不同 worker 按任务特点选模型（查资料用快，写作用贵）")
    print("   - 降本逻辑：决策次数少（贵），执行次数多（免费），整体成本大降")
    print("   - 对比手写 L08：全程单一模型 → 按角色选模型")
    print()
    print("🎓 LangGraph 主干段（L01-L06）全部完成！")
    print("   接下来 L07-L08 进入横向框架对比（CrewAI / AutoGen）")
    print("=" * 64)


if __name__ == "__main__":
    main()
