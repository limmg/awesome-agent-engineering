"""任务注册表：崩溃后的重做量有界（AgentOps L06）。

现状缺口：
    AsyncSqliteSaver 已经在每个超级步落盘 State，但服务层没有任务注册——
    崩溃后没人知道「哪些任务没跑完、该从哪继续」，checkpoint 躺在库里等于没有。

本模块给任务一个注册表：
    - jobs 表（task_id/thread_id/status/主题/时间戳）
    - 提交即登记、完成即更新、启动时扫描 running 状态的孤儿任务
    - 恢复语义：同 thread_id 以 None 输入重新 ainvoke → langgraph 从最后 checkpoint 续跑
      （已完成的 researcher 不重跑）+ 已执行副作用靠 L04 幂等键不重放

重做量从「全部」压到「最后一个未完成节点」。

与 frontier-L10 TaskLedger 的边界（重要，不重叠）：
    账本管「跨多次运行的语义增量」（第三次运行接着第二次的结论做，不重复研究）；
    本课管「单次运行的执行恢复」（进程崩在 writer 节点，重启后从 checkpoint 续跑）。
    账本是工作层，durable 是执行层，互补不重叠。
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

from .logging_config import get_logger

log = get_logger("jobs")

_DB_PATH = "jobs_registry.db"

# 任务状态
STATUS_PENDING = "pending"        # 已提交，未开始
STATUS_RUNNING = "running"        # 正在跑
STATUS_DONE = "done"              # 正常完成
STATUS_FAILED = "failed"          # 失败
STATUS_AWAITING_APPROVAL = "awaiting_approval"  # 等审批（L05）
STATUS_INTERRUPTED = "interrupted"  # 中断（可恢复）


def _get_db_path() -> Path:
    here = Path(__file__).resolve().parent
    return here.parent.parent / _DB_PATH


def _connect() -> sqlite3.Connection:
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            task_id     TEXT PRIMARY KEY,
            thread_id   TEXT NOT NULL,
            topic       TEXT NOT NULL,
            status      TEXT NOT NULL,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL,
            result_json TEXT,
            error       TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_thread ON jobs(thread_id)")
    conn.commit()
    return conn


def submit_job(topic: str, thread_id: str | None = None) -> dict:
    """提交一个研究任务，登记进注册表。

    Returns:
        {"task_id": ..., "thread_id": ..., "status": "pending", "topic": ...}
    """
    task_id = f"job-{uuid.uuid4().hex[:8]}"
    thread_id = thread_id or f"thread-{uuid.uuid4().hex[:8]}"
    now = time.time()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO jobs (task_id, thread_id, topic, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, thread_id, topic, STATUS_PENDING, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    log.info(f"提交任务 {task_id}（thread={thread_id}, topic={topic}）")
    return {"task_id": task_id, "thread_id": thread_id, "status": STATUS_PENDING, "topic": topic}


def update_status(task_id: str, status: str, result: dict | None = None, error: str | None = None):
    """更新任务状态。"""
    import json
    conn = _connect()
    try:
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ?, result_json = ?, error = ? WHERE task_id = ?",
            (status, time.time(),
             json.dumps(result, ensure_ascii=False) if result else None,
             error, task_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_job(task_id: str) -> dict | None:
    """查询单个任务。"""
    import json
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT task_id, thread_id, topic, status, created_at, updated_at, result_json, error "
            "FROM jobs WHERE task_id = ?", (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0], "thread_id": row[1], "topic": row[2], "status": row[3],
            "created_at": row[4], "updated_at": row[5],
            "result": json.loads(row[6]) if row[6] else None, "error": row[7],
        }
    finally:
        conn.close()


def get_job_by_thread(thread_id: str) -> dict | None:
    """按 thread_id 查任务。"""
    import json
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT task_id, thread_id, topic, status, created_at, updated_at, result_json, error "
            "FROM jobs WHERE thread_id = ? ORDER BY updated_at DESC LIMIT 1", (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0], "thread_id": row[1], "topic": row[2], "status": row[3],
            "created_at": row[4], "updated_at": row[5],
            "result": json.loads(row[6]) if row[6] else None, "error": row[7],
        }
    finally:
        conn.close()


def find_orphans() -> list[dict]:
    """扫描 running/interrupted 状态的孤儿任务（启动时恢复用）。

    这些是「进程崩了没跑完」的任务——重启后应尝试续跑。
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT task_id, thread_id, topic, status, updated_at "
            "FROM jobs WHERE status IN (?, ?) ORDER BY updated_at",
            (STATUS_RUNNING, STATUS_INTERRUPTED),
        ).fetchall()
        return [{"task_id": r[0], "thread_id": r[1], "topic": r[2],
                 "status": r[3], "updated_at": r[4]} for r in rows]
    finally:
        conn.close()


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict]:
    """列出任务（可按状态过滤）。"""
    conn = _connect()
    try:
        if status:
            rows = conn.execute(
                "SELECT task_id, thread_id, topic, status, updated_at "
                "FROM jobs WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT task_id, thread_id, topic, status, updated_at "
                "FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [{"task_id": r[0], "thread_id": r[1], "topic": r[2],
                 "status": r[3], "updated_at": r[4]} for r in rows]
    finally:
        conn.close()


def set_db_path_for_test(path: str):
    """测试用：覆盖注册表路径（隔离）。"""
    global _DB_PATH
    _DB_PATH = path
