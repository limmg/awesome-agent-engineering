"""
Lesson 04 — 并行执行与 Map-Reduce：fan-out 爆发
==================================================
前三课的所有图都是【串行】的（一个节点完再下一个）。
但很多任务可以【并行】——比如同时查 3 个子问题的答案。
本课用 LangGraph 的 Send API 实现 fan-out（爆发）+ map-reduce（合并）。

核心问题：
    Agent L08 README 提到「无法并行」——手写 for 循环只能串行。
    并行能大幅省时间：3 个子任务串行约 15 秒，并行约 5 秒。

三个部分：
  ① 并行 map-reduce：主题 → 拆分 → 并行 worker ×N → reduce 合并
  ② 对比串行 vs 并行的耗时（亲眼看到并行加速）
  ③ 理解 reducer：为什么并行结果不会互相覆盖

映射：agent-lessons/08_multi_agent（手写串行 executor，README 提了无法并行）
运行：python workflow-lessons/04_parallel_mapreduce/code.py
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
import time
from typing import Annotated
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_community.chat_models import ChatZhipuAI
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send  # ⭐ 本课主角：触发并行 fan-out

CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"


# ════════════════════════════════════════════════════════════
# 第 1 步：定义 State（含 reducer 字段——并行的关键）
# ════════════════════════════════════════════════════════════
class ResearchState(TypedDict):
    """研究 State。

    results 字段用了 operator.add reducer——这是并行的关键：
    多个 worker 并行写回 results 时，reducer 自动把它们【拼接】而不是覆盖。
    如果没有 reducer，后写的 worker 会覆盖先写的（数据丢失）。
    """
    topic: str                                   # 研究主题
    subtasks: list[str]                          # 拆分出的子问题
    results: Annotated[list[str], operator.add]  # ⭐ reducer：并行结果自动拼接
    report: str                                  # 最终报告


# worker 的输入 State（和主图 State 不同——Send 传的是这个）
class WorkerInput(TypedDict):
    """单个 worker 收到的输入：一个子问题 + 主题上下文。"""
    subtask: str
    topic: str


# ════════════════════════════════════════════════════════════
# 第 2 步：map-reduce 三节点
# ════════════════════════════════════════════════════════════

# ── map 节点：把大主题拆成 N 个子问题 ──
def make_split_node(llm):
    """创建 split 节点（用闭包注入 llm）。

    对比 Agent L08 手写：
        手写的 planner() 只拆步骤，但后续 executor 是【串行】逐步执行的。
        这里的 split 拆完后，子问题会被【并行】分发。
    """
    def split(state: ResearchState):
        topic = state["topic"]
        resp = llm.invoke(
            f"你是研究规划师。把「{topic}」拆成 3 个具体的研究子问题，"
            f"每行一个，只要问题本身，不要编号不要解释。"
        )
        subs = [s.strip().lstrip("0123456789.、） ") for s in resp.content.strip().split("\n") if s.strip()]
        subs = subs[:3]  # 最多 3 个
        print(f"  [split] 主题「{topic}」拆出 {len(subs)} 个子问题：")
        for i, s in enumerate(subs, 1):
            print(f"         {i}. {s}")
        return {"subtasks": subs}
    return split


# ── 路由函数：返回多个 Send，触发并行 fan-out（本课核心）──
def route_to_workers(state: ResearchState):
    """⭐⭐⭐ 本课最关键的函数。

    返回一个 [Send, Send, Send] 列表。每个 Send 代表"派一个 worker 实例处理这个子问题"。
    LangGraph 收到多个 Send 后，会【同时】启动多个 worker 节点实例（并行）。

    对比 Agent L08 手写：
        手写是 for subtask in steps: result = executor(subtask)  ← 串行，一个接一个
        这里是 return [Send('worker', ...) for subtask]            ← 并行，同时跑
    """
    sends = [Send("worker", {"subtask": s, "topic": state["topic"]}) for s in state["subtasks"]]
    print(f"  [route] 并行派发 {len(sends)} 个 worker（fan-out）")
    return sends


# ── worker 节点：处理单个子问题（会被并行调用 N 次）──
def make_worker_node(llm):
    """创建 worker 节点。

    注意：worker 收到的 state 是 WorkerInput（不是 ResearchState），
    因为 Send 传入的是 {'subtask': ..., 'topic': ...}。
    worker 处理完返回 {'results': [单个结果]}，
    reducer(operator.add) 会把多个 worker 的 results 拼起来。
    """
    def worker(state: WorkerInput):
        subtask = state["subtask"]
        topic = state["topic"]
        resp = llm.invoke(
            f"主题：{topic}\n请针对子问题「{subtask}」用 2-3 句话简要回答，给出关键信息。"
        )
        result = f"【{subtask}】\n{resp.content.strip()}"
        print(f"  [worker] ✓ 完成一个子问题")
        return {"results": [result]}  # ⭐ reducer 会自动拼接多个 worker 的结果
    return worker


# ── reduce 节点：合并所有并行结果成报告 ──
def make_reduce_node(llm):
    """创建 reduce 节点：把多个 worker 的结果汇总成一份连贯报告。

    注意：reduce 返回 {} 或写新字段（report），不要再写 results——
    因为 results 有 reducer，重复写会重复追加（验证时踩过这个坑）。
    """
    def reduce_results(state: ResearchState):
        all_results = state["results"]
        print(f"  [reduce] 合并 {len(all_results)} 个并行结果")

        # 用 LLM 把零散结果整理成连贯报告
        combined = "\n\n".join(all_results)
        resp = llm.invoke(
            f"你是研究报告撰写者。把以下研究结果整理成一份结构化报告，"
            f"包含概述和要点。不要编造新信息：\n\n{combined}"
        )
        return {"report": resp.content.strip()}  # 写到新字段 report，不碰 results
    return reduce_results


# ════════════════════════════════════════════════════════════
# 第 3 步：组装并行 map-reduce 图
# ════════════════════════════════════════════════════════════
def build_parallel_graph(llm):
    """组装 map-reduce 并行图。

    流程：START → split →(Send ×N 并行)→ worker ×N → reduce → END

    对比前 3 课的串行图：
        L01 supervisor：researcher→analyst→writer 一个接一个
        本课：3 个 worker 同时跑（并行）
    """
    builder = StateGraph(ResearchState)
    builder.add_node("split", make_split_node(llm))
    builder.add_node("worker", make_worker_node(llm))
    builder.add_node("reduce", make_reduce_node(llm))

    builder.add_edge(START, "split")
    builder.add_conditional_edges("split", route_to_workers)  # ⭐ 返回多个 Send = 并行
    builder.add_edge("worker", "reduce")  # 所有并行 worker 完成后汇入 reduce
    builder.add_edge("reduce", END)

    return builder.compile()


# ════════════════════════════════════════════════════════════
# 实验 1：并行 map-reduce 完整流程
# ════════════════════════════════════════════════════════════
def part_1_parallel_mapreduce(graph):
    """演示完整的并行 map-reduce。

    观察三个阶段：
        map（split）：主题 → 3 个子问题
        fan-out（并行 worker）：3 个 worker 同时处理（不是排队！）
        reduce：合并成报告
    """
    print("\n" + "─" * 60)
    print("实验 1：并行 map-reduce（主题 → 拆分 → 并行查询 → 合并）")
    print("─" * 60)
    topic = "2024 年 AI Agent 技术的重要进展"
    print(f"📋 研究主题：{topic}")
    print("\n流程：split(拆分) → worker ×3(并行) → reduce(合并)\n")

    t0 = time.time()
    result = graph.invoke({
        "topic": topic, "subtasks": [], "results": [], "report": ""
    })
    elapsed = time.time() - t0

    print(f"\n{'━' * 60}")
    print(f"✅ 并行耗时：{elapsed:.1f}s")
    print(f"{'━' * 60}")
    print(f"\n📊 研究报告：\n{result['report']}")
    print(f"\n💡 3 个子问题并行处理，总共 {elapsed:.1f}s。")
    print(f"   如果串行（一个接一个），大约需要 {elapsed * 3:.1f}s——并行省了近 2/3。")


# ════════════════════════════════════════════════════════════
# 实验 2：对比串行 vs 并行（亲手测出加速比）
# ════════════════════════════════════════════════════════════
def part_2_serial_vs_parallel(llm):
    """用同样的 3 个子问题，分别串行和并行跑，对比耗时。

    串行：for subtask in subtasks: answer = llm.invoke(subtask)  # 一个接一个
    并行：用图的 Send 机制（实验 1 已演示）
    """
    print("\n\n" + "─" * 60)
    print("实验 2：串行 vs 并行 耗时对比")
    print("─" * 60)

    subtasks = [
        "AI Agent 的工具调用能力进展",
        "多智能体协作框架的发展",
        "Agent 记忆机制的突破",
    ]
    print(f"📋 3 个相同的子问题，分别用串行/并行处理\n")

    # ── 串行：for 循环一个接一个（手写 L08 的方式）──
    print("【串行版】（for 循环，一个接一个）")
    t0 = time.time()
    serial_results = []
    for i, sub in enumerate(subtasks, 1):
        resp = llm.invoke(f"用1句话简要回答：{sub}")
        serial_results.append(resp.content.strip()[:40])
        print(f"  [{i}/3] 完成（{time.time()-t0:.1f}s）")
    serial_time = time.time() - t0
    print(f"  串行总耗时：{serial_time:.1f}s")

    # ── 并行：用图的 Send 机制 ──
    print(f"\n【并行版】（Send fan-out，3 个同时跑）")
    # 用 Send 做纯并行：3 个 worker 同时启动
    pbuilder = StateGraph(RemixState)
    def pworker(state):
        r = llm.invoke(f"用1句话简要回答：{state['subtask']}").content.strip()[:40]
        return {"results": [r]}
    pbuilder.add_node("pw", pworker)
    pbuilder.add_conditional_edges(START, lambda s: [Send("pw", {"subtask": x}) for x in subtasks])
    pbuilder.add_edge("pw", END)
    pgraph = pbuilder.compile()

    t1 = time.time()
    presult = pgraph.invoke({"results": []})
    parallel_time = time.time() - t1
    print(f"  并行总耗时：{parallel_time:.1f}s（3 个同时完成）")

    # ── 对比 ──
    print(f"\n📊 加速比：")
    print(f"   串行：{serial_time:.1f}s")
    print(f"   并行：{parallel_time:.1f}s")
    print(f"   加速：{serial_time/parallel_time:.1f}x（省了 {serial_time-parallel_time:.1f}s）")
    print(f"\n💡 并行不是「免费」的——它消耗的 LLM 调用次数和串行一样（都是 3 次），")
    print(f"   但【墙钟时间】大幅缩短。这就是 map-reduce 的价值。")


class RemixState(TypedDict):
    """实验 2 的简易并行 State。"""
    subtask: str
    results: Annotated[list[str], operator.add]


# ════════════════════════════════════════════════════════════
# 实验 3：理解 reducer（为什么并行不会互相覆盖）
# ════════════════════════════════════════════════════════════
def part_3_reducer_demo():
    """演示 reducer 的作用：没有 reducer 会覆盖，有 reducer 会拼接。

    这是并行写回同一字段时的核心机制——必须理解，否则数据会丢。
    """
    print("\n\n" + "─" * 60)
    print("实验 3：reducer 的作用（为什么并行结果不覆盖）")
    print("─" * 60)

    print("""
模拟 3 个并行 worker 各自返回 {"results": ["答案X"]}：

情况 1：results 字段【没有 reducer】（普通 list）
    worker 1 返回 ["答案A"] → results = ["答案A"]
    worker 2 返回 ["答案B"] → results = ["答案B"]  ⚠️ 覆盖了 A！
    worker 3 返回 ["答案C"] → results = ["答案C"]  ⚠️ 覆盖了 B！
    最终 results = ["答案C"]  ← 丢了 2/3 的数据！

情况 2：results 字段【有 reducer = operator.add】（本课用法）
    worker 1 返回 ["答案A"] → results = [] + ["答案A"] = ["答案A"]
    worker 2 返回 ["答案B"] → results = ["答案A"] + ["答案B"] = ["答案A","答案B"]
    worker 3 返回 ["答案C"] → results = ["答案A","答案B"] + ["答案C"]
    最终 results = ["答案A","答案B","答案C"]  ✅ 全部保留！

代码对比：
    # 没有 reducer（会被覆盖）
    results: list[str]

    # 有 reducer（自动拼接，并行的正确做法）
    results: Annotated[list[str], operator.add]
""")
    print("💡 规则：只要一个字段会被【并行】写回，就必须配 reducer。")
    print("   这是 LangGraph 并行的第一铁律，忘了就会丢数据。")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 04 — 并行执行与 Map-Reduce：fan-out 爆发")
    print("=" * 64)
    print("用 Send API 实现并行，兑现 Agent L08「无法并行」的遗憾。")
    print("映射：agent-lessons/08_multi_agent（手写串行 executor）")

    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    print("\n🔧 构建并行 map-reduce 图...")
    graph = build_parallel_graph(llm)
    print("✅ 图已编译（split → worker×N 并行 → reduce）")

    part_1_parallel_mapreduce(graph)    # 完整并行流程
    part_2_serial_vs_parallel(llm)      # 串行 vs 并行对比
    part_3_reducer_demo()               # reducer 机制

    print("\n" + "=" * 64)
    print("✅ 并行 Map-Reduce 小结：")
    print("   - Send(node, arg) 触发并行：条件边返回 [Send, Send, ...] = fan-out")
    print("   - reducer(operator.add) 合并：并行结果自动拼接，不覆盖")
    print("   - map-reduce：split(拆分) → worker×N(并行) → reduce(合并)")
    print("   - 并行省【墙钟时间】（3 任务并行约 5s，串行约 15s），但 LLM 调用次数不变")
    print("   - 对比手写 L08：for 循环串行 → Send 并行（兑现「无法并行」的遗憾）")
    print("   - 铁律：被并行写回的字段【必须】配 reducer，否则丢数据")
    print("=" * 64)


if __name__ == "__main__":
    main()
