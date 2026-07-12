"""L12 · 最小复现：多 Agent 记忆共享。

复现的 idea：
    多个 Agent 协作时，共享一个记忆库（A 的发现 B 能 recall），
    比各自独立记忆，整体任务完成质量更高。

最小实现（≤200 行核心逻辑）：
    - 两个 Agent（A 研究"协议"，B 研究"生态"）
    - 共享模式：A 的发现存入共享库，B 能 recall
    - 独立模式：各存各的，互不可见
    - 对照：B 的研究里是否引用了 A 的发现（共享应更高）

对照实验：
    共享记忆 vs 独立记忆，看"信息复用率"（B 引用 A 发现的比例）。

跑法：
    cd frontier-lessons/12_frontier_tracking
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


class MiniMemory:
    """最小记忆库（不用 Chroma，简化为 dict + 关键词匹配）。

    最小复现的原则：去掉一切非必要工程细节。
    真实场景用 L01 的 MemoryStore（Chroma + embedding）。
    """

    def __init__(self):
        self._store: list[dict] = []  # [{content, agent, topic}]

    def remember(self, content: str, agent: str, topic: str):
        self._store.append({"content": content, "agent": agent, "topic": topic})

    def recall(self, query: str, exclude_agent: str = "") -> list[str]:
        """召回相关记忆，可排除自己写的（只看别人的）。"""
        hits = []
        for item in self._store:
            if exclude_agent and item["agent"] == exclude_agent:
                continue  # 排除自己的（测"别人写的能不能 recall"）
            # 关键词匹配（最小复现，不用 embedding）
            if any(w in query for w in item["content"][:10].split()) or \
               any(w in item["content"] for w in query.split()[:3]):
                hits.append(item["content"])
        return hits


class MiniAgent:
    """最小 Agent：研究一个主题，产出发现，可查记忆。"""

    def __init__(self, name: str, memory: MiniMemory):
        self.name = name
        self.memory = memory
        self.findings: list[str] = []

    def research(self, topic: str, use_shared_memory: bool = True):
        """研究一个主题。"""
        # 查记忆（共享模式：查别人的；独立模式：不查）
        prior = []
        if use_shared_memory:
            prior = self.memory.recall(topic, exclude_agent=self.name)

        # 模拟研究产出（预设，代表 LLM+搜索的结果）
        if "协议" in topic:
            finding = f"MCP 协议基于 JSON-RPC 2.0，由 Anthropic 2024 发布"
        elif "生态" in topic:
            finding = f"MCP 生态覆盖文件系统/数据库/搜索等场景"
        elif "SDK" in topic:
            finding = f"MCP SDK 支持 Python/TypeScript/Java"
        else:
            finding = f"关于 {topic} 的发现"

        # 如果有共享记忆，在发现里引用别人的结论（信息复用）
        if prior:
            finding += f"（关联：{prior[0][:30]}...）"

        self.findings.append(finding)
        # 存入记忆
        self.memory.remember(finding, self.name, topic)
        return finding


def run_experiment(shared: bool) -> dict:
    """跑一次实验：共享 vs 独立记忆。

    Returns: {"agent_b_referenced_a": bool, "findings": [...]}
    """
    if shared:
        # 共享模式：两个 Agent 用同一个记忆库
        memory = MiniMemory()
        agent_a = MiniAgent("A", memory)
        agent_b = MiniAgent("B", memory)
    else:
        # 独立模式：各用各的记忆库
        agent_a = MiniAgent("A", MiniMemory())
        agent_b = MiniAgent("B", MiniMemory())

    # Agent A 研究"协议"（先跑，把发现存入记忆）
    agent_a.research("MCP 协议设计", use_shared_memory=False)

    # Agent B 研究"生态"（共享模式能 recall A 的协议发现）
    b_finding = agent_b.research("MCP 生态场景", use_shared_memory=shared)

    # 检查 B 的发现是否引用了 A 的结论
    referenced = "关联" in b_finding and "JSON-RPC" in b_finding

    return {
        "shared": shared,
        "agent_a_finding": agent_a.findings[0] if agent_a.findings else "",
        "agent_b_finding": b_finding,
        "b_referenced_a": referenced,
    }


def main():
    print("=" * 60)
    print("L12 最小复现：多 Agent 记忆共享")
    print("=" * 60)

    print("\n── 复现的 idea ───────────────────────────────────")
    print("  多个 Agent 共享一个记忆库（A 的发现 B 能 recall），")
    print("  比各自独立记忆，信息复用率更高。")
    print("\n── 最小实现 ─────────────────────────────────────")
    print("  2 个 Agent（A 研究'协议'，B 研究'生态'）")
    print("  MiniMemory: dict + 关键词匹配（不用 Chroma/embedding）")
    print("  对照：共享 vs 独立，看 B 是否引用 A 的发现")

    # ── 对照实验 ──────────────────────────────────────────
    print("\n── 对照实验 ─────────────────────────────────────")

    print("\n【独立记忆模式】")
    result_indep = run_experiment(shared=False)
    print(f"  Agent A 发现: {result_indep['agent_a_finding'][:50]}")
    print(f"  Agent B 发现: {result_indep['agent_b_finding'][:50]}")
    print(f"  B 引用 A? {'是 ✅' if result_indep['b_referenced_a'] else '否 ❌'}")

    print("\n【共享记忆模式】")
    result_shared = run_experiment(shared=True)
    print(f"  Agent A 发现: {result_shared['agent_a_finding'][:50]}")
    print(f"  Agent B 发现: {result_shared['agent_b_finding'][:50]}")
    print(f"  B 引用 A? {'是 ✅' if result_shared['b_referenced_a'] else '否 ❌'}")

    # ── 结果解读 ──────────────────────────────────────────
    print("\n── 结果解读 ─────────────────────────────────────")
    print(f"  独立模式信息复用率: {'100%' if result_indep['b_referenced_a'] else '0%'}")
    print(f"  共享模式信息复用率: {'100%' if result_shared['b_referenced_a'] else '0%'}")

    if result_shared["b_referenced_a"] and not result_indep["b_referenced_a"]:
        print(f"\n  ✅ 复现成功：共享记忆让 Agent B 复用了 A 的发现（信息复用 0→100%）")
        print(f"  → 支持 idea：多 Agent 共享记忆 > 独立记忆")
    else:
        print(f"\n  ⚠️ 结果不符合预期（见 repro_note.md 的归因）")

    # ── 方法论回顾 ────────────────────────────────────────
    print("\n── 方法论回顾 ───────────────────────────────────")
    print("  ① 抽核心 idea：多 Agent 共享记忆 > 独立记忆")
    print("  ② 最小实现：MiniMemory + MiniAgent（去掉了 Chroma/embedding/LLM）")
    print("  ③ 对照实验：共享 vs 独立，看信息复用率")
    print("  ④ 复现笔记：见 repro_note.md")

    print("\n" + "=" * 60)
    print("✅ 最小复现 = 核心idea的最小实现 + 一个对照实验")
    print("📝 复现笔记见 repro_note.md（诚实记录结果和差异）")
    print("=" * 60)


if __name__ == "__main__":
    main()
