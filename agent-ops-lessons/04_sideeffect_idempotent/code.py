"""L04 · 副作用与幂等：能重放的才敢自动化
==================================================

本脚本演示故障⑥（危险副作用）前半 before/after：
    - before（裸奔）：reviewer 打回重写导致 publish 被走到两次 → 重复发布（事故）。
    - after（开幂等）：同 thread+同内容的 publish 第二次返回 no-op（幂等重放）。
    还演示 dry-run（上线前演练）。

核心认知：工具副作用三级分类（只读 / 可重放 / 不可重放）。
幂等键 = hash(thread_id + 内容指纹)，是 L06 断点续跑不重放副作用的地基。

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


# ────────────────────────────────────────────────────────────
# Part 1 · 副作用三级分类
# ────────────────────────────────────────────────────────────

def demo_side_effect_classification():
    print("=" * 64)
    print("  Part 1 · 工具副作用三级分类（核心认知）")
    print("=" * 64)
    print()
    print("  ┌─────────────────┬──────────────────────┬──────────────────────┐")
    print("  │ 级别             │ 例子                  │ 重复执行的后果        │")
    print("  ├─────────────────┼──────────────────────┼──────────────────────┤")
    print("  │ ① 只读           │ search / browser      │ 无害（无副作用）      │")
    print("  │ ② 可重放         │ 写本地文件             │ 覆盖无害（最终一致）  │")
    print("  │ ③ 不可重放       │ 发布/发邮件/下单       │ 事故（每次有外部副作用）│")
    print("  └─────────────────┴──────────────────────┴──────────────────────┘")
    print()
    print("  💡 现状 research-assistant 全是 ① 只读，所以「没出过事」是因为「没做过危险的事」。")
    print("     一旦加 ③ 不可重放动作（如 publish_report），重复执行 = 事故。")


# ────────────────────────────────────────────────────────────
# Part 2 · 幂等键 before/after
# ────────────────────────────────────────────────────────────

async def demo_idempotency_before_after():
    from research_assistant import publish

    # 用临时 db（不污染生产）
    import tempfile, os
    tmpdir = tempfile.mkdtemp()
    publish._DB_PATH = os.path.join(tmpdir, "publish.db")

    print("\n" + "=" * 64)
    print("  Part 2 · 故障⑥前半 —— reviewer 打回重写导致重复发布")
    print("=" * 64)

    # ── before：裸奔（无幂等，每次都真发布）──
    print("\n【before · 裸奔】（无幂等键，每次 publish 都真执行）")
    publish_log = []
    def publish_naked(content):
        publish_log.append(content)  # 模拟真的发布（写了外部系统）
        return {"published": True, "seq": len(publish_log)}
    # reviewer 打回一次：writer 重写 → publish 被走到两次（同一版内容）
    r1 = publish_naked("第一版报告")
    r2 = publish_naked("第一版报告")  # 同内容，重复执行
    print(f"  第 1 次 publish：seq={r1['seq']}  → 真的发布了 ⚠️")
    print(f"  第 2 次 publish：seq={r2['seq']}  → 又发布了一次 ☠️（重复发布事故）")
    print(f"  实际发布次数：{len(publish_log)}（应该 1 次，实际 2 次）")

    # ── after：开幂等 ──
    print("\n【after · 开幂等键】（同 thread+同内容第二次 no-op）")
    # 清空临时 db 重新测
    publish._DB_PATH = os.path.join(tempfile.mkdtemp(), "publish.db")
    r1 = publish.publish_report("thread-1", "第一版报告")
    r2 = publish.publish_report("thread-1", "第一版报告")  # 同内容 → 幂等
    r3 = publish.publish_report("thread-1", "第二版（改进）")  # 不同内容 → 新发布
    print(f"  第 1 次 publish：published={r1['published']}, replay={r1['idempotent_replay']}, seq={r1['seq']}  → 真发布")
    print(f"  第 2 次 publish：published={r2['published']}, replay={r2['idempotent_replay']}  → 幂等 no-op ✅")
    print(f"  第 3 次 publish（内容变了）：published={r3['published']}, replay={r3['idempotent_replay']}, seq={r3['seq']}  → 新发布")
    history = publish.get_publish_history("thread-1")
    print(f"  发布历史记录数：{len(history)}（去重后）")


# ────────────────────────────────────────────────────────────
# Part 3 · dry-run 演练
# ────────────────────────────────────────────────────────────

async def demo_dry_run():
    from research_assistant import publish, config
    import tempfile, os
    publish._DB_PATH = os.path.join(tempfile.mkdtemp(), "publish.db")
    config.settings.__dict__["publish_dry_run"] = True

    print("\n" + "=" * 64)
    print("  Part 3 · dry-run（上线前演练）")
    print("=" * 64)
    r = publish.publish_report("thread-1", "报告内容")
    print(f"\n  dry-run 结果：published={r['published']}, dry_run={r['dry_run']}")
    print(f"  output_path={r['output_path']}（None，没真写）")
    print(f"  发布历史：{publish.get_publish_history('thread-1')}（空，没真记）")
    print(f"\n  💡 dry-run 只打印将执行的动作不真执行——上线前验证副作用路径正确，不留痕迹。")


async def main():
    print("L04 · 副作用与幂等 —— 故障⑥危险副作用（前半）")
    print()
    demo_side_effect_classification()
    await demo_idempotency_before_after()
    await demo_dry_run()
    print("\n" + "=" * 64)
    print("  结论")
    print("=" * 64)
    print("  · 副作用三级：只读 / 可重放 / 不可重放。不可重放的动作必须有幂等键。")
    print("  · 幂等键 = hash(thread_id + 内容指纹)：同内容第二次 no-op，内容变了算新发布")
    print("  · dry-run：上线前演练，打印动作不真执行")
    print("  · 幂等是 L06 断点续跑不重放副作用的地基")


if __name__ == "__main__":
    asyncio.run(main())
