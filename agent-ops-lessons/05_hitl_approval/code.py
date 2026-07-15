"""L05 · 人在环审批（HITL）：危险动作的门闸
==================================================

本脚本演示故障⑥后半 before/after：
    - before（裸奔）：publish 未经批准直接执行。
    - after（开 HITL）：publish 前 interrupt 暂停等人审批，
      批准 → 发布，否决 → 诚实收尾；演示跨进程恢复（审批可以隔夜）。

核心机制：langgraph interrupt() + Command(resume=...)。
    - interrupt 在节点内打断 → State 存入 checkpointer → 进程可退出
    - 带 resume 值重新 invoke 同 thread → 继续

实测（langgraph 1.2.7）：
    第一次 ainvoke → 返回 {'__interrupt__': [Interrupt(value=...)]}，state.next=('publish',)
    第二次 ainvoke(Command(resume={...})) → interrupt 返回 resume 值，继续执行

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


async def demo_interrupt_resume():
    """演示 interrupt/resume 审批流（最小可复现）。"""
    from typing import Annotated
    from typing_extensions import TypedDict
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import interrupt, Command

    class S(TypedDict):
        report: str
        published: str
        rejected: str

    def publish_with_approval(state):
        # interrupt 暂停：进程可退出，等 Command(resume=...) 恢复
        decision = interrupt({"action": "publish", "preview": state["report"][:50]})
        approved = isinstance(decision, dict) and decision.get("approved")
        if approved:
            return {"published": "✅ 已发布"}
        return {"rejected": "🚫 被否决，走诚实收尾"}

    builder = StateGraph(S)
    builder.add_node("publish", publish_with_approval)
    builder.add_edge(START, "publish")
    builder.add_edge("publish", END)

    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "demo"}}

    print("=" * 64)
    print("  Part 1 · interrupt/resume 审批流（实测 langgraph 1.2.7）")
    print("=" * 64)

    # 第一次：interrupt 暂停
    print("\n【场景 A：提交后等审批（进程可退出）】")
    r1 = await graph.ainvoke({"report": "报告内容", "published": "", "rejected": ""}, config=cfg)
    print(f"  第 1 次 ainvoke 结果：{'__interrupt__' in r1 and '已暂停 ⏸️' or '完成'}")
    state = await graph.aget_state(cfg)
    print(f"  state.next = {state.next}（停在 publish，等审批）")
    print(f"  💡 此时进程可以退出——checkpointer 存了中断状态，重启后能恢复（审批可隔夜）")

    # 批准：恢复
    print("\n【场景 B：批准 → resume → 发布】")
    r2 = await graph.ainvoke(Command(resume={"approved": True, "comment": "同意"}), config=cfg)
    print(f"  Command(resume={{approved:True}}) 后：published={r2.get('published', '(无)')}")

    # 重置，演示否决
    saver2 = InMemorySaver()
    graph2 = builder.compile(checkpointer=saver2)
    cfg2 = {"configurable": {"thread_id": "demo2"}}
    print("\n【场景 C：否决 → resume → 诚实收尾】")
    await graph2.ainvoke({"report": "报告", "published": "", "rejected": ""}, config=cfg2)
    r3 = await graph2.ainvoke(Command(resume={"approved": False, "comment": "不要"}), config=cfg2)
    print(f"  Command(resume={{approved:False}}) 后：rejected={r3.get('rejected', '(无)')}")


def demo_policy_strategies():
    """演示三级审批策略。"""
    print("\n" + "=" * 64)
    print("  Part 2 · 审批策略分层（自主-控制主线的教科书）")
    print("=" * 64)
    print()
    print("  ┌──────────────┬──────────────────────┬────────────────────────────┐")
    print("  │ 策略          │ 行为                  │ 适用场景                    │")
    print("  ├──────────────┼──────────────────────┼────────────────────────────┤")
    print("  │ auto         │ 全过（HITL 形同虚设）  │ 演示基线 / 低风险动作        │")
    print("  │ first_only   │ 仅首次发布审（默认）   │ 最实用：幂等重放免审        │")
    print("  │ always       │ 每次都审（最保守）     │ 高风险：每次发布都确认      │")
    print("  └──────────────┴──────────────────────┴────────────────────────────┘")
    print()
    print("  💡 first_only 是默认——首次发布必审，后续幂等重放（同内容）免审。")
    print("     这避免了「幂等 no-op 还要人点确认」的橡皮图章，又不放过真正的首次发布。")


async def main():
    print("L05 · 人在环审批 —— 故障⑥后半：危险动作的门闸")
    print()
    await demo_interrupt_resume()
    demo_policy_strategies()
    print("\n" + "=" * 64)
    print("  结论")
    print("=" * 64)
    print("  · interrupt/resume：节点内打断 → checkpointer 存状态 → 进程可退出 → 同 thread resume")
    print("  · 审批策略分层：只拦不可重放且首次的动作（first_only），不把人变橡皮图章")
    print("  · 跨进程恢复：审批可以隔夜——checkpointer 存了中断状态")
    print("  · 自主-控制主线：闸只拦该拦的（首次危险动作），其余放行")


if __name__ == "__main__":
    asyncio.run(main())
