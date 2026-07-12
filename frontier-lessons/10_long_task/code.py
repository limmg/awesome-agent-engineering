"""L10 · 长任务演示：TaskLedger 跨会话推进 + 增量简报。

演示流程：
    1. 模拟第 1 次运行：创建 TODO 计划，执行部分，标 done
    2. 模拟第 2 次运行：断点续跑（next_actions），执行剩余，产出增量简报
    3. 模拟第 3 次运行：发现新信息，加新 TODO，增量简报标注修正
    4. 展示三次的简报演进

跑法：
    cd frontier-lessons/10_long_task
    python code.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_RA_SRC = _HERE.parents[1] / "portfolio-projects" / "research-assistant" / "src"
sys.path.insert(0, str(_RA_SRC))


def main():
    from research_assistant.task_ledger import TaskLedger

    print("=" * 60)
    print("L10 长任务：TaskLedger 跨会话推进 + 增量简报")
    print("=" * 60)

    topic = "MCP 生态的演进"

    # 用固定目录（Windows sqlite 无文件锁问题）
    db_path = _HERE / "demo_ledger.db"
    if db_path.exists():
        db_path.unlink()
    ledger = TaskLedger(db_path=str(db_path))

    # ── 第 1 次运行：创建计划 + 执行部分 ─────────────────────
    print(f"\n{'═'*50}")
    print(f"第 1 次运行：{topic}")
    print(f"{'═'*50}")

    # 首次运行：从主题创建 TODO 计划
    subtopics = [
        "查 MCP 协议设计",
        "查 MCP SDK 支持的语言",
        "查 MCP 生态覆盖场景",
    ]
    items = ledger.plan_from_topic(topic, subtopics)
    print(f"  创建 TODO 计划：{len(items)} 个子任务")
    for it in items:
        print(f"    [{it.status}] {it.title}")

    # 模拟执行前两个（标 done）
    ledger.update_status(items[0].id, "done", "MCP 基于 JSON-RPC 2.0，由 Anthropic 2024 发布")
    ledger.update_status(items[1].id, "done", "支持 Python/TypeScript/Java")
    print(f"\n  执行完毕 2/3：")
    for it in ledger.get_tasks(topic):
        print(f"    [{it.status}] {it.title}")

    brief1 = ledger.generate_incremental_brief(topic, [
        "MCP 基于 JSON-RPC 2.0",
        "SDK 支持 Python/TypeScript/Java",
    ])
    print(f"\n  简报：")
    print(brief1)

    # ── 第 2 次运行：断点续跑 ───────────────────────────────
    print(f"\n{'═'*50}")
    print(f"第 2 次运行：断点续跑")
    print(f"{'═'*50}")

    # 断点续跑：next_actions 告诉我们还差什么
    actions = ledger.next_actions(topic)
    print(f"  next_actions: {len(actions)} 个待办")
    for a in actions:
        print(f"    [{a.status}] {a.title}")

    if actions:
        # 执行剩余的
        ledger.update_status(actions[0].id, "done", "覆盖文件系统/数据库/搜索等场景")
        print(f"\n  执行剩余任务...")

    brief2 = ledger.generate_incremental_brief(topic, [
        "MCP 生态覆盖文件系统/数据库/搜索等场景",
    ])
    print(f"\n  增量简报：")
    print(brief2)

    # ── 第 3 次运行：发现新信息 + 修正 ───────────────────────
    print(f"\n{'═'*50}")
    print(f"第 3 次运行：发现新信息 + 修正旧结论")
    print(f"{'═'*50}")

    # 新发现 → 加新 TODO（动态计划）
    ledger.add_task(topic, "查 MCP 2025 路线图")
    print(f"  新发现 → 动态加 TODO: '查 MCP 2025 路线图'")

    actions3 = ledger.next_actions(topic)
    print(f"  next_actions: {len(actions3)} 个待办")

    brief3 = ledger.generate_incremental_brief(topic, [
        "MCP 2025 路线图聚焦互操作性",
        "修正：MCP 协议实际基于 JSON-RPC 2.0 标准草案（旧结论漏了版本号）",
    ])
    print(f"\n  增量简报（含修正）：")
    print(brief3)

    # ── 总结 ──────────────────────────────────────────────
    print(f"\n{'═'*50}")
    print(f"三次运行演进总结")
    print(f"{'═'*50}")
    print(f"  第1次：创建计划 3 项，完成 2 项，首次简报")
    print(f"  第2次：断点续跑，完成剩余 1 项，增量简报（🆕新增）")
    print(f"  第3次：动态加 TODO，增量简报（🆕新增 + ✏️修正）")
    print(f"  → 每次接着上次做，不从头重写")

    # 清理
    db_path.unlink(missing_ok=True)

    print(f"\n" + "=" * 60)
    print("✅ TaskLedger = TODO树 + 断点续跑 + 增量简报")
    print("📋 与记忆/checkpoint 分工：经验/进度/对话三维度")
    print("=" * 60)


if __name__ == "__main__":
    main()
