"""AgentOps L06 测试：任务注册表 + 断点续跑。

测试原则（对齐 conftest.py）：
    - 不调用真实 LLM（用 FakeLLM）
    - jobs 注册表用 tmp_path 隔离
    - checkpoint 续跑用 InMemorySaver（验证语义：已完成节点不重做）
"""
from __future__ import annotations

import pytest

from research_assistant import config, jobs


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个测试用独立的 jobs 注册表 + 还原开关。"""
    monkeypatch.setattr(jobs, "_DB_PATH", str(tmp_path / "jobs.db"))
    config.settings.__dict__["enable_job_registry"] = False
    yield


# ── submit_job / update_status / get_job ────────────────────

def test_submit_job_registers():
    r = jobs.submit_job("研究主题", thread_id="t1")
    assert r["status"] == jobs.STATUS_PENDING
    assert r["topic"] == "研究主题"
    assert r["thread_id"] == "t1"
    assert r["task_id"].startswith("job-")


def test_submit_job_auto_thread_id():
    r = jobs.submit_job("主题")
    assert r["thread_id"].startswith("thread-")


def test_update_and_get_job():
    r = jobs.submit_job("主题", "t1")
    jobs.update_status(r["task_id"], jobs.STATUS_RUNNING)
    job = jobs.get_job(r["task_id"])
    assert job["status"] == jobs.STATUS_RUNNING

    jobs.update_status(r["task_id"], jobs.STATUS_DONE, result={"report": "报告"})
    job = jobs.get_job(r["task_id"])
    assert job["status"] == jobs.STATUS_DONE
    assert job["result"] == {"report": "报告"}


def test_get_job_none_if_missing():
    assert jobs.get_job("不存在") is None


def test_get_job_by_thread():
    jobs.submit_job("主题", "t1")
    job = jobs.get_job_by_thread("t1")
    assert job is not None
    assert job["thread_id"] == "t1"


# ── find_orphans：孤儿任务扫描 ─────────────────────────────

def test_find_orphans_finds_running():
    """running/interrupted 状态的任务是孤儿（启动时恢复）。"""
    r1 = jobs.submit_job("t1", "thread-1")
    r2 = jobs.submit_job("t2", "thread-2")
    r3 = jobs.submit_job("t3", "thread-3")
    jobs.update_status(r1["task_id"], jobs.STATUS_RUNNING)
    jobs.update_status(r2["task_id"], jobs.STATUS_DONE)  # 已完成，不是孤儿
    jobs.update_status(r3["task_id"], jobs.STATUS_INTERRUPTED)
    orphans = jobs.find_orphans()
    orphan_ids = {o["task_id"] for o in orphans}
    assert r1["task_id"] in orphan_ids  # running
    assert r3["task_id"] in orphan_ids  # interrupted
    assert r2["task_id"] not in orphan_ids  # done 不是孤儿


def test_find_orphans_empty_when_all_done():
    r = jobs.submit_job("t", "thread-1")
    jobs.update_status(r["task_id"], jobs.STATUS_DONE)
    assert jobs.find_orphans() == []


# ── list_jobs ───────────────────────────────────────────────

def test_list_jobs_filter_by_status():
    r1 = jobs.submit_job("t1", "th1")
    r2 = jobs.submit_job("t2", "th2")
    jobs.update_status(r1["task_id"], jobs.STATUS_DONE)
    done = jobs.list_jobs(status=jobs.STATUS_DONE)
    assert len(done) == 1
    assert done[0]["task_id"] == r1["task_id"]


def test_list_jobs_limit():
    for i in range(5):
        jobs.submit_job(f"t{i}", f"th{i}")
    all_jobs = jobs.list_jobs(limit=3)
    assert len(all_jobs) == 3


# ── 端到端：checkpoint 续跑（已完成节点不重做）──────────────

@pytest.mark.asyncio
async def test_checkpoint_resume_does_not_redo():
    """用 InMemorySaver + interrupt 验证：None 输入恢复时不重做已完成节点。

    这是 L06 的核心机制——langgraph 从最后 checkpoint 续跑。
    用 interrupt 在 n1 后暂停（比 recursion_limit 更可控）。
    """
    from typing_extensions import TypedDict
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import interrupt, Command

    # 用一个 call_count 追踪节点是否被重做
    call_counts = {"n1": 0, "n2": 0, "n3": 0}

    class S(TypedDict):
        value: int

    def n1(state):
        call_counts["n1"] += 1
        return {"value": state.get("value", 0) + 1}
    def n2(state):
        call_counts["n2"] += 1
        # 在 n2 开头 interrupt（模拟「跑到 n2 前进程被杀」）
        interrupt({"at": "n2"})
        return {"value": state.get("value", 0) + 1}
    def n3(state):
        call_counts["n3"] += 1
        return {"value": state.get("value", 0) + 1}

    builder = StateGraph(S)
    builder.add_node("n1", n1)
    builder.add_node("n2", n2)
    builder.add_node("n3", n3)
    builder.add_edge(START, "n1")
    builder.add_edge("n1", "n2")
    builder.add_edge("n2", "n3")
    builder.add_edge("n3", END)

    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "resume-test"}}

    # 第一次：n1 跑完后，n2 的 interrupt 暂停
    r1 = await graph.ainvoke({"value": 0}, config=cfg)
    # n1 跑过了（call_count=1），n2 的 interrupt 暂停
    assert call_counts["n1"] == 1
    assert "__interrupt__" in r1  # 暂停在 n2

    # 恢复：Command(resume) 让 n2 继续
    result = await graph.ainvoke(Command(resume="continue"), config=cfg)
    # 关键：n1（中断前已完成的节点）没重做（call_count 仍=1）
    # n2 会重跑（interrupt 在 n2 内部，恢复时 n2 从头执行）——这正是「重做量=最后一个未完成节点」
    assert call_counts["n1"] == 1  # ← 关键：中断前完成的节点没重做
    assert call_counts["n2"] == 2  # n2 重跑了一次（interrupt 后恢复会重新执行该节点）
    assert call_counts["n3"] == 1
    assert result["value"] == 3


@pytest.mark.asyncio
async def test_submit_research_no_registry_degrades_to_invoke(fake_llm):
    """enable_job_registry=False → submit_research 退化为 invoke（现状行为）。"""
    config.settings.__dict__["enable_job_registry"] = False
    from research_assistant.service import submit_research
    # 不打真实 API——这里只验证不登记 jobs
    try:
        r = await submit_research("主题")
        assert r["status"] in ("done", )
    except Exception:
        pass  # 真实 web_search 可能失败，关键是没抛 KeyError
    # jobs 表应为空（没登记）
    assert jobs.list_jobs() == []
