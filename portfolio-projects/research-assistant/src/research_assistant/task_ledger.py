"""任务账本：跨会话的长任务状态管理（Frontier L10）。

长任务三要素：
    ① 任务状态持久化：TODO 树（已完成/进行中/待办），区别于对话 checkpoint
       也区别于记忆——它是「计划」不是「经验」
    ② 断点续跑：新会话先读账本决定「接着做什么」而非「从头做」
    ③ 增量产出：diff 式简报（上次结论 + 本次新增 + 修正项）

与记忆的区别：
    记忆（L01-L02）= 经验的存储（发生过什么、学到了什么）
    账本（本课）= 计划的存储（要做什么、做到哪了、还差什么）
    两者不互斥：记忆提供"经验"，账本提供"进度"。

持久化：sqlite（比 Chroma 轻，适合结构化 TODO 树）。
降级：enable_ledger=false 或 sqlite 不可用时返回空，不影响现有功能。
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .logging_config import get_logger

log = get_logger("task_ledger")


@dataclass
class TaskItem:
    """TODO 树的一个节点。"""
    id: str
    topic: str               # 大主题（如"MCP 生态演进"）
    title: str               # 本节点要做什么（如"查 MCP SDK 语言支持"）
    status: str = "todo"     # todo / in_progress / done
    result: str = ""         # 完成后的结论/产出
    run_count: int = 0       # 被执行过几次（断点续跑计数）
    parent_id: str = ""      # 父节点（TODO 树层级）
    created_at: float = 0.0
    updated_at: float = 0.0


class TaskLedger:
    """任务账本：TODO 树的持久化 + 断点续跑决策 + 增量简报生成。

    核心区别（vs Checkpointer vs MemoryStore）：
        - Checkpointer：存对话状态快照（恢复对话）
        - MemoryStore：存经验（recall 相关旧记忆）
        - TaskLedger：存计划（接下来做什么、做到哪了）
        三者协同：记忆提供经验、账本提供进度、checkpoint 恢复对话。

    持久化：sqlite（结构化 TODO 树，比向量库合适）。
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or settings.ledger_db_path or "task_ledger.db"
        self._init_db()

    def _init_db(self):
        """初始化 sqlite 表。"""
        parent = Path(self._db_path).parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'todo',
                result TEXT DEFAULT '',
                run_count INTEGER DEFAULT 0,
                parent_id TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_topic ON tasks(topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
        conn.commit()
        conn.close()
        log.info(f"任务账本初始化：{self._db_path}")

    def add_task(self, topic: str, title: str, parent_id: str = "") -> TaskItem:
        """添加一个 TODO 项。"""
        import hashlib
        task_id = hashlib.md5(f"{topic}{title}{time.time()}".encode()).hexdigest()[:12]
        now = time.time()
        item = TaskItem(
            id=task_id, topic=topic, title=title, status="todo",
            parent_id=parent_id, created_at=now, updated_at=now,
        )
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT INTO tasks (id, topic, title, status, result, run_count, parent_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, item.topic, item.title, item.status, item.result,
             item.run_count, item.parent_id, item.created_at, item.updated_at),
        )
        conn.commit()
        conn.close()
        log.debug(f"添加任务：{title}")
        return item

    def get_tasks(self, topic: str) -> list[TaskItem]:
        """获取某主题的所有任务。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tasks WHERE topic=? ORDER BY created_at", (topic,)
        ).fetchall()
        conn.close()
        return [TaskItem(
            id=r["id"], topic=r["topic"], title=r["title"], status=r["status"],
            result=r["result"], run_count=r["run_count"], parent_id=r["parent_id"],
            created_at=r["created_at"], updated_at=r["updated_at"],
        ) for r in rows]

    def update_status(self, task_id: str, status: str, result: str = ""):
        """更新任务状态（断点续跑的关键：标记做完什么了）。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE tasks SET status=?, result=?, run_count=run_count+1, updated_at=? WHERE id=?",
            (status, result, time.time(), task_id),
        )
        conn.commit()
        conn.close()
        log.debug(f"任务 {task_id} → {status}")

    def next_actions(self, topic: str) -> list[TaskItem]:
        """断点续跑的核心：决定「接下来做什么」。

        策略：
            1. 先看有没有 todo 的（还没做的）
            2. 再看有没有 in_progress 的（做了一半的）
            3. 全 done → 返回空（任务完成了）
        """
        tasks = self.get_tasks(topic)
        todo = [t for t in tasks if t.status == "todo"]
        in_prog = [t for t in tasks if t.status == "in_progress"]
        return todo + in_prog  # todo 优先

    def is_first_run(self, topic: str) -> bool:
        """是否是某主题的第一次运行（账本无记录）。"""
        return len(self.get_tasks(topic)) == 0

    def generate_incremental_brief(self, topic: str, new_findings: list[str]) -> str:
        """生成增量简报：上次结论 + 本次新增 + 修正项。

        这是长任务的核心产出——不是从零重写，是 diff 式更新。
        """
        tasks = self.get_tasks(topic)
        done = [t for t in tasks if t.status == "done"]

        lines = [f"# 增量简报：{topic}\n"]

        if not done:
            # 第一次运行：完整报告
            lines.append("## 首次研究（无历史）\n")
            lines.append("本次是首次研究，产出完整基线：\n")
            for f in new_findings:
                lines.append(f"- 🆕 {f[:100]}")
            return "\n".join(lines)

        # 增量模式
        lines.append("## 历史结论（已确认）\n")
        for t in done:
            if t.result:
                lines.append(f"- ➡️ {t.title}: {t.result[:80]}")

        lines.append("\n## 本次新增\n")
        for f in new_findings:
            # 简单判断是新增还是修正
            is_correction = any(kw in f for kw in ["修正", "更正", "实际上", "并非"])
            marker = "✏️ 修正" if is_correction else "🆕 新增"
            lines.append(f"- {marker}: {f[:100]}")

        lines.append("\n## 不变项\n")
        unchanged = [t for t in done if t.result and not any(
            kw in f for f in new_findings for kw in [t.result[:20]]
        )]
        for t in unchanged:
            lines.append(f"- ➡️ {t.title}: 仍成立")

        return "\n".join(lines)

    def plan_from_topic(self, topic: str, subtopics: list[str]) -> list[TaskItem]:
        """从主题 + 子问题创建 TODO 计划（首次运行时）。"""
        if not self.is_first_run(topic):
            return self.get_tasks(topic)  # 已有计划，直接返回

        items = []
        for sub in subtopics:
            item = self.add_task(topic, sub)
            items.append(item)
        log.info(f"为主题 {topic} 创建 {len(items)} 个 TODO 项")
        return items


# ── 全局单例 ──────────────────────────────────────────────
_ledger: TaskLedger | None = None


def get_ledger() -> TaskLedger | None:
    """获取全局 TaskLedger 单例。

    enable_ledger=false 时返回 None（完全不介入）。
    """
    global _ledger
    if not settings.enable_ledger:
        return None
    if _ledger is None:
        _ledger = TaskLedger()
    return _ledger
