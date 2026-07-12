"""任务账本测试（Frontier L10）。

测试不依赖真实 LLM，用临时 sqlite。
"""
from __future__ import annotations

import pytest

from research_assistant.task_ledger import TaskLedger, TaskItem


@pytest.fixture
def ledger(tmp_path):
    """临时 sqlite 的账本。"""
    return TaskLedger(db_path=str(tmp_path / "test_ledger.db"))


# ── 基本增删改查 ──────────────────────────────────────────────
def test_add_and_get_task(ledger):
    """添加任务后应能查到。"""
    ledger.add_task("MCP", "查 MCP 协议设计")
    tasks = ledger.get_tasks("MCP")
    assert len(tasks) == 1
    assert tasks[0].title == "查 MCP 协议设计"
    assert tasks[0].status == "todo"


def test_update_status(ledger):
    """更新状态后应反映在查询结果里。"""
    item = ledger.add_task("MCP", "查 SDK")
    ledger.update_status(item.id, "done", "支持 Python/TS/Java")
    tasks = ledger.get_tasks("MCP")
    assert tasks[0].status == "done"
    assert "Python" in tasks[0].result
    assert tasks[0].run_count == 1


def test_update_increments_run_count(ledger):
    """多次更新应累加 run_count。"""
    item = ledger.add_task("MCP", "查协议")
    ledger.update_status(item.id, "in_progress")
    ledger.update_status(item.id, "done", "结果")
    tasks = ledger.get_tasks("MCP")
    assert tasks[0].run_count == 2


# ── 断点续跑 ──────────────────────────────────────────────────
def test_next_actions_returns_todo(ledger):
    """next_actions 应返回未完成的任务。"""
    t1 = ledger.add_task("MCP", "任务1")
    t2 = ledger.add_task("MCP", "任务2")
    t3 = ledger.add_task("MCP", "任务3")
    ledger.update_status(t1.id, "done", "完成1")

    actions = ledger.next_actions("MCP")
    assert len(actions) == 2  # t2, t3 未完成
    titles = [a.title for a in actions]
    assert "任务2" in titles
    assert "任务3" in titles


def test_next_actions_empty_when_all_done(ledger):
    """全完成时 next_actions 应返回空。"""
    t1 = ledger.add_task("MCP", "任务1")
    ledger.update_status(t1.id, "done", "完成")
    assert ledger.next_actions("MCP") == []


def test_is_first_run(ledger):
    """无记录时应判定首次运行。"""
    assert ledger.is_first_run("MCP")
    ledger.add_task("MCP", "任务")
    assert not ledger.is_first_run("MCP")


# ── 增量简报 ──────────────────────────────────────────────────
def test_incremental_brief_first_run(ledger):
    """首次运行应产出完整基线（无历史结论）。"""
    brief = ledger.generate_incremental_brief("MCP", ["发现1", "发现2"])
    assert "首次研究" in brief
    assert "🆕" in brief


def test_incremental_brief_with_history(ledger):
    """有历史时应产出增量（上次结论+本次新增）。"""
    t1 = ledger.add_task("MCP", "查协议")
    ledger.update_status(t1.id, "done", "MCP 基于 JSON-RPC")

    brief = ledger.generate_incremental_brief("MCP", [
        "MCP 生态在扩展",
        "修正：MCP 实际基于 JSON-RPC 2.0",
    ])
    assert "历史结论" in brief
    assert "本次新增" in brief
    assert "🆕" in brief  # 新增
    assert "✏️" in brief  # 修正


def test_incremental_brief_marks_corrections(ledger):
    """含修正信号词的发现应标 ✏️ 修正。"""
    t1 = ledger.add_task("MCP", "查协议")
    ledger.update_status(t1.id, "done", "旧结论")

    brief = ledger.generate_incremental_brief("MCP", [
        "实际上 MCP 基于 JSON-RPC",
    ])
    assert "✏️" in brief


# ── plan_from_topic ───────────────────────────────────────────
def test_plan_from_topic_creates_tasks(ledger):
    """首次运行应创建 TODO 计划。"""
    subs = ["子问题1", "子问题2", "子问题3"]
    items = ledger.plan_from_topic("MCP", subs)
    assert len(items) == 3
    assert all(i.status == "todo" for i in items)


def test_plan_from_topic_returns_existing(ledger):
    """非首次运行应返回已有计划（不重复创建）。"""
    ledger.plan_from_topic("MCP", ["子1"])
    items = ledger.plan_from_topic("MCP", ["子1", "子2"])
    assert len(items) == 1  # 不重复创建


# ── 多主题隔离 ────────────────────────────────────────────────
def test_topics_are_isolated(ledger):
    """不同主题的任务应隔离。"""
    ledger.add_task("MCP", "MCP任务")
    ledger.add_task("RAG", "RAG任务")
    assert len(ledger.get_tasks("MCP")) == 1
    assert len(ledger.get_tasks("RAG")) == 1
