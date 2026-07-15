"""L06 · 断点续跑：崩溃后的重做量有界
==================================================

本脚本演示故障④（进程崩溃）before/after：
    - before（裸奔）：进程崩在 writer 节点，从头全部重跑（重做量无界）。
    - after（开任务注册表 + checkpoint 续跑）：从最后 checkpoint 续跑，
      已完成的 researcher 不重做、已执行的副作用靠 L04 幂等键不重放。

实测（langgraph 1.2.7）：
    - 进程崩前完成的节点：恢复时不重做（call_count 不变）
    - 中断所在的节点：恢复时从头重新执行（这是「重做量=最后一个未完成节点」的精确含义）
    - 同 thread_id 以 None 输入 ainvoke → 从 checkpoint 续跑

与 frontier-L10 TaskLedger 的边界：
    账本管「跨多次运行的语义增量」，本课管「单次运行的执行恢复」，互补不重叠。

跑法（零外部依赖）：
    python code.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "portfolio-projects" / "research-assistant" / "src"))


async def demo_checkpoint_resume():
    """演示 checkpoint 续跑：已完成节点不重做。"""
    from typing_extensions import TypedDict
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import interrupt, Command

    # 模拟 research-assistant 的拓扑：research_team → writer → reviewer
    # 用 call_count 追踪每个节点被调了几次
    call_counts = {"research_team": 0, "writer": 0, "reviewer": 0}

    class S(TypedDict):
        topic: str
        report: str

    def research_team(state):
        call_counts["research_team"] += 1
        return {"topic": state.get("topic", "")}  # 模拟检索完成

    def writer(state):
        call_counts["writer"] += 1
        # 模拟「跑到 writer 时进程被杀」—— interrupt 暂停
        interrupt({"at": "writer", "reason": "进程崩溃演示"})
        return {"report": "报告内容"}

    def reviewer(state):
        call_counts["reviewer"] += 1
        return {"report": state.get("report", "")}

    builder = StateGraph(S)
    builder.add_node("research_team", research_team)
    builder.add_node("writer", writer)
    builder.add_node("reviewer", reviewer)
    builder.add_edge(START, "research_team")
    builder.add_edge("research_team", "writer")
    builder.add_edge("writer", "reviewer")
    builder.add_edge("reviewer", END)

    print("=" * 64)
    print("  Part 1 · checkpoint 续跑（实测 langgraph 1.2.7）")
    print("=" * 64)

    # ── before：裸奔（无 checkpoint，崩溃=全部重跑）──
    print("\n【before · 裸奔】（崩溃后从头重跑）")
    print("  research_team → writer(💥崩) → 重启 → research_team(重做!) → writer → reviewer")
    print("  重做量：全部（research_team 的检索白做了）")
    print("  副作用：如果 writer 前有 publish，会重复发布（L04 幂等才挡住）")

    # ── after：checkpoint 续跑 ──
    print("\n【after · checkpoint 续跑】（同 thread None 输入恢复）")
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "crash-demo"}}

    # 第一次：跑到 writer interrupt 暂停（模拟崩溃）
    r1 = await graph.ainvoke({"topic": "研究主题", "report": ""}, config=cfg)
    print(f"  第 1 次跑：research_team={call_counts['research_team']}, writer={call_counts['writer']}")
    print(f"           → 暂停在 writer（{'__interrupt__' in r1 and '是' or '否'}），research_team 已完成")

    # 「进程退出再重启」：同 thread_id，None 输入恢复
    r2 = await graph.ainvoke(Command(resume="继续"), config=cfg)
    print(f"  恢复后跑：research_team={call_counts['research_team']}(没重做!), "
          f"writer={call_counts['writer']}, reviewer={call_counts['reviewer']}")
    print(f"  报告：{r2.get('report', '(无)')}")
    print(f"\n  💡 关键：research_team（崩溃前完成的）没重做——重做量压到「最后一个未完成节点」")
    print(f"     writer 会重跑一次（interrupt 在 writer 内，恢复时该节点从头执行）——")
    print(f"     这正是「重做量=最后一个未完成节点」的精确含义")


def demo_jobs_registry():
    """演示任务注册表（孤儿任务扫描）。"""
    from research_assistant import jobs
    import tempfile, os
    jobs._DB_PATH = os.path.join(tempfile.mkdtemp(), "jobs.db")

    print("\n" + "=" * 64)
    print("  Part 2 · 任务注册表（孤儿任务扫描 + 恢复）")
    print("=" * 64)

    # 提交几个任务
    j1 = jobs.submit_job("主题A", "thread-A")
    j2 = jobs.submit_job("主题B", "thread-B")
    j3 = jobs.submit_job("主题C", "thread-C")

    # j1 跑完了，j2 崩在 running，j3 中断
    jobs.update_status(j1["task_id"], jobs.STATUS_DONE, result={"report": "A 报告"})
    jobs.update_status(j2["task_id"], jobs.STATUS_RUNNING)
    jobs.update_status(j3["task_id"], jobs.STATUS_INTERRUPTED)

    print("\n  任务状态：")
    for j in jobs.list_jobs():
        print(f"    {j['task_id']}  {j['status']:<12}  {j['topic']}")

    # 启动时扫描孤儿（running/interrupted）
    orphans = jobs.find_orphans()
    print(f"\n  孤儿任务（启动时恢复）：{len(orphans)} 个")
    for o in orphans:
        print(f"    {o['task_id']}  {o['status']:<12}  {o['topic']}  → resume_job 恢复")
    print(f"\n  💡 j1（done）不是孤儿不恢复；j2（running）、j3（interrupted）是孤儿，启动时续跑")


async def main():
    print("L06 · 断点续跑 —— 故障④进程崩溃：重做量有界")
    print()
    await demo_checkpoint_resume()
    demo_jobs_registry()
    print("\n" + "=" * 64)
    print("  结论")
    print("=" * 64)
    print("  · checkpoint 续跑：同 thread None 输入 → 从最后 checkpoint 恢复，已完成节点不重做")
    print("  · 重做量 = 最后一个未完成节点（而非全部）——「有界」的精确含义")
    print("  · 副作用不重放：靠 L04 幂等键（同内容 no-op）")
    print("  · jobs 注册表：发现孤儿任务，启动时自动续跑")
    print("  · 与 frontier-L10 账本的边界：账本管跨运行增量，checkpoint 管单次运行恢复")


if __name__ == "__main__":
    asyncio.run(main())
