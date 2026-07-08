"""State 定义：图的"数据形状"。

两层图，两个 State：
    - ResearchState：并行研究子图（map-reduce 的工作面）
    - SystemState：父图（对话 + 研究 + 报告 + 审稿）

共享字段 findings（同名 + 同 reducer）是子图结果回流父图的桥梁。
这是 workflow-L05「共享 State 通信」模式。
"""
from __future__ import annotations

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict

from langgraph.graph.message import add_messages


# ════════════════════════════════════════════════════════════
# 子图 State（并行研究子系统）
# ════════════════════════════════════════════════════════════
class ResearchState(TypedDict):
    """并行研究子图的 State。

    findings 用 reducer（operator.add）：多个并行 researcher 的返回自动拼接，
    不互相覆盖。这是 L04 并行写回 + L05 共享 State 的核心机制——
    没有这个 reducer，并行结果会丢失。
    """
    topic: str
    subtopics: list[str]
    # ⭐ reducer 合并并行结果（L04 map-reduce 关键）
    findings: Annotated[list[str], operator.add]
    research_summary: str


# ════════════════════════════════════════════════════════════
# 父图 State（完整研究系统）
# ════════════════════════════════════════════════════════════
class SystemState(TypedDict):
    """整个研究系统的 State（父图）。

    综合：
        - messages：对话历史（add_messages reducer，L01 supervisor 模式）
        - findings：从子图回流的研究发现（与 ResearchState.findings 同名 + 同 reducer）
        - research_summary：子图产出的研究摘要
        - report：最终报告
        - review_decision：审稿结论（阶段 2）
        - rewrite_count：已重写次数（阶段 2，防死循环）
        - feedback：审稿反馈（传给 writer 改进）
    """
    messages: Annotated[list[Any], add_messages]
    findings: Annotated[list[str], operator.add]
    research_summary: str
    report: str
    review_decision: str
    rewrite_count: int
    feedback: str
