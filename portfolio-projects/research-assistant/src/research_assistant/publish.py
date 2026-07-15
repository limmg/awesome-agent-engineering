"""副作用工具 + 幂等键（AgentOps L04）。

为什么需要它（现状缺口）：
    现状 research-assistant 全是只读工具（search/browser），所以「没出过事」是因为
    「没做过危险的事」。一旦加发布动作就是裸奔——reviewer 打回重写会导致 publish 被走到
    两次（重复发布），断点续跑（L06）会重放已执行的副作用。

工具副作用三级分类（本课核心认知）：
    ① 只读      search / browser          重复执行无害
    ② 可重放    写本地文件                 重复执行覆盖无害（最终状态一致）
    ③ 不可重放  发布 / 发邮件 / 下单        重复执行 = 事故（每次都有外部副作用）

幂等键：hash(thread_id + 内容指纹)。已发布的键直接返回上次结果（no-op）。
这是 L06 断点续跑不重放副作用的地基——崩溃恢复时，已 publish 的键不会再执行。

dry-run：打印将执行的动作不真执行（上线前演练）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from .config import settings
from .logging_config import get_logger

log = get_logger("publish")

# 发布注册表 sqlite 路径（幂等键的去重表）
_DB_PATH = "publish_registry.db"


def _get_db_path() -> Path:
    """发布注册表路径（可被测试覆盖）。"""
    here = Path(__file__).resolve().parent
    # 放在项目根（research-assistant/）下
    return here.parent.parent / _DB_PATH


def _connect() -> sqlite3.Connection:
    """连接发布注册表（不存在则建表）。"""
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS publishes (
            idempotency_key TEXT PRIMARY KEY,
            thread_id       TEXT NOT NULL,
            content_hash    TEXT NOT NULL,
            output_path     TEXT,
            published_at    REAL NOT NULL,
            result_json     TEXT
        )
    """)
    conn.commit()
    return conn


def idempotency_key(thread_id: str, content: str) -> str:
    """幂等键：thread_id + 内容指纹。

    同一 thread + 同一内容 → 同一 key → 重复发布返回上次结果（no-op）。
    内容变了（reviewer 打回重写后内容不同）→ 不同 key → 算新发布。

    为什么用内容指纹而不只是 thread_id：
        如果只用 thread_id，reviewer 打回重写后的「改进版」会被当成重复不发布——
        但那是用户想要的更新。内容指纹让「内容相同才算重复」。
    """
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    thread_hash = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:8]
    return f"{thread_hash}:{content_hash}"


def publish_report(thread_id: str, content: str, dry_run: bool | None = None) -> dict:
    """发布报告（不可重放副作用，带幂等键）。

    Args:
        thread_id: 会话 ID（幂等键的一部分）
        content: 报告内容（幂等键的一部分）
        dry_run: True=只打印不真执行（None 时读 config.publish_dry_run）

    Returns:
        {"published": bool, "idempotent_replay": bool, "key": str, "output_path": str, "seq": int}

    幂等行为：
        - 同一 key 已发布过 → published=True, idempotent_replay=True（no-op，返回上次结果）
        - 新 key → 真执行（写 outputs/ + 注册表），published=True, idempotent_replay=False
        - dry_run → 只打印不写，published=False
    """
    if dry_run is None:
        dry_run = settings.publish_dry_run

    key = idempotency_key(thread_id, content)

    # dry-run：只打印不执行
    if dry_run:
        log.info(f"[dry-run] 将发布报告（key={key}, thread={thread_id}, {len(content)} 字），不真执行")
        return {"published": False, "idempotent_replay": False, "key": key,
                "output_path": None, "seq": 0, "dry_run": True}

    conn = _connect()
    try:
        # 幂等检查：同一 key 已发布？
        row = conn.execute(
            "SELECT output_path, result_json FROM publishes WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is not None:
            # 幂等重放：返回上次结果，不重复执行副作用
            output_path, result_json = row
            log.info(f"幂等重放：key={key} 已发布过，返回上次结果（no-op）")
            result = json.loads(result_json) if result_json else {}
            result["idempotent_replay"] = True
            return result

        # 新发布：写 outputs/ + 注册表
        here = Path(__file__).resolve().parent
        outputs_dir = here.parent.parent / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        # 统计已有发布数作 seq
        seq = conn.execute(
            "SELECT COUNT(*) FROM publishes WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0] + 1
        output_path = outputs_dir / f"report_{thread_id}_{seq}.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        result = {
            "published": True, "idempotent_replay": False, "key": key,
            "output_path": str(output_path), "seq": seq, "dry_run": False,
        }
        conn.execute(
            "INSERT INTO publishes (idempotency_key, thread_id, content_hash, output_path, published_at, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key, thread_id, key.split(":")[1], str(output_path), time.time(), json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
        log.info(f"报告已发布：key={key}, output={output_path}, seq={seq}")
        return result
    finally:
        conn.close()


def get_publish_history(thread_id: str) -> list[dict]:
    """查询某个 thread 的发布历史（给观测/审计用）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT idempotency_key, output_path, published_at, result_json "
            "FROM publishes WHERE thread_id = ? ORDER BY published_at",
            (thread_id,),
        ).fetchall()
        return [{"key": r[0], "output_path": r[1], "published_at": r[2],
                 "result": json.loads(r[3]) if r[3] else {}} for r in rows]
    finally:
        conn.close()


# ── 节点工厂：可选的 publish 节点（reviewer PASS 后）─────────

def _needs_approval(thread_id: str, content: str) -> bool:
    """策略判断：这次 publish 是否需要人审批（AgentOps L05）。

    三级策略（config.hitl_policy）：
        - auto：全过（HITL 开了等于没开，演示基线用）
        - first_only：仅首次发布审（默认，最实用——后续幂等 no-op 免审）
        - always：每次都审（最保守）
    """
    policy = settings.hitl_policy
    if policy == "auto":
        return False
    if policy == "always":
        return True
    # first_only：查注册表，已发布过（幂等重放）→ 免审
    history = get_publish_history(thread_id)
    key = idempotency_key(thread_id, content)
    for h in history:
        if h["key"] == key:
            return False  # 幂等重放，免审
    return True  # 首次发布，必审


def make_publish_node():
    """发布节点工厂：reviewer PASS 后执行 publish_report（带幂等 + HITL 审批）。

    enable_publish=False 时图里根本不加这个节点（现状等价）。
    enable_hitl=True 时：publish 前 interrupt() 暂停等人审批，
        批准 → 继续 publish；否决 → 走诚实收尾（标 truncated，不发布）。
    """
    def publish_node(state) -> dict:
        from langgraph.types import interrupt
        report = state.get("report", "")
        thread_id = "default"  # thread_id 在 configurable 里，节点内取默认

        # AgentOps L05：HITL 审批门（enable_hitl 时）
        if settings.enable_hitl and _needs_approval(thread_id, report):
            # interrupt 暂停：进程可退出，带 resume 值重新 invoke 同 thread 继续
            # resume 值约定：{"approved": True/False, "comment": "..."}
            decision = interrupt({
                "action": "publish_report",
                "thread_id": thread_id,
                "content_preview": report[:200],
                "content_length": len(report),
                "policy": settings.hitl_policy,
            })
            # decision 是 Command(resume=...) 传入的值
            approved = False
            if isinstance(decision, dict):
                approved = decision.get("approved", False)
            elif isinstance(decision, str):
                approved = decision.lower() in ("approved", "yes", "ok", "批准", "同意")

            if not approved:
                # 否决 → 诚实收尾（不发布，标 truncated）
                log.info(f"publish 被人否决，走诚实收尾（不发布）")
                return {
                    "publish_result": {"published": False, "rejected": True},
                    "truncated": True,
                    "messages": [],
                }

        # 批准（或无需审批）→ 执行 publish（幂等）
        result = publish_report(thread_id, report)
        return {
            "publish_result": result,
            "messages": [],  # 不污染对话历史
        }
    return publish_node


def set_db_path_for_test(path: str):
    """测试用：覆盖发布注册表路径（隔离）。"""
    global _DB_PATH
    _DB_PATH = path
