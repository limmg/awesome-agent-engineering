"""L05 · 反思进研究回路：冲突检测 + 定向补研演示。

演示流程：
    1. 往记忆库存入旧结论（"MCP 基于 gRPC"——故意错的）
    2. 模拟新研究发现（"MCP 基于 JSON-RPC"——正确的，与旧结论冲突）
    3. check_conflicts 检测冲突 → 生成定向补研问题
    4. 演示双通道路由：冲突 → re_research → research_team
    5. 演示 writer 的修正说明

用 Mock LLM 演示（不依赖真实 API），但接入真实 check_conflicts 逻辑。

跑法：
    cd frontier-lessons/05_reflection_research
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


# Mock LLM：模拟冲突检测的 judge
class MockConflictLLM:
    """模拟冲突检测 LLM：新发现含'JSON-RPC'且旧结论含'gRPC'时判冲突。"""
    def invoke(self, prompt, **kw):
        class R:
            content = ""
        if "只回复一个词" in prompt:
            # 简单判断：prompt 里同时有 JSON-RPC 和 gRPC → 冲突
            if "JSON-RPC" in prompt and "gRPC" in prompt:
                R.content = "冲突"
            elif "JSON-RPC" in prompt and "JSON-RPC" in prompt:
                R.content = "一致"
            else:
                R.content = "无关"
        elif "生成一个定向补研问题" in prompt:
            R.content = "MCP 协议到底基于 JSON-RPC 还是 gRPC？请查证官方文档"
        return R()


def main():
    from research_assistant.memory import MemoryStore, SemanticMemory
    import time
    import research_assistant.nodes as nodes
    import research_assistant.config as config

    print("=" * 60)
    print("L05 反思进研究回路：冲突检测 + 定向补研")
    print("=" * 60)

    # 强制开启 memory（演示用）
    config.settings.__dict__["enable_memory"] = True
    config.settings.__dict__["enable_skills"] = False

    # 清掉可能存在的全局单例
    nodes._memory_store = None

    # 用临时目录做记忆库
    demo_dir = _HERE / "demo_mem"
    if demo_dir.exists():
        shutil.rmtree(demo_dir, ignore_errors=True)
    demo_dir.mkdir(exist_ok=True)

    # ── 1. 存入旧结论（故意错的）────────────────────────────
    print("\n── 步骤1：记忆库存入旧结论 ─────────────────────")
    store = MemoryStore(persist_path=str(demo_dir))
    store._chroma = None  # 强制内存模式
    # 直接写入一条语义记忆（模拟之前研究得出的结论）
    old_mem = SemanticMemory(
        id="old1",
        topic="MCP",
        conclusion="MCP 协议基于 gRPC 框架实现",  # 故意错的
        evidence="早期推测，未经证实",
        timestamp=time.time(),
        confidence=0.5,
    )
    store._semantic.append(old_mem)
    print(f"  旧结论：{old_mem.conclusion}（置信度{old_mem.confidence}）")
    print(f"  ⚠️ 这是错的——MCP 实际基于 JSON-RPC，但 Agent 上次得出了错误结论")

    # 设置全局 memory_store
    nodes._memory_store = store

    # ── 2. 新研究发现（正确的，与旧结论冲突）────────────────
    print("\n── 步骤2：新研究发现（与旧结论冲突）──────────────")
    new_findings = [
        "【MCP 协议】发现：MCP 协议基于 JSON-RPC 2.0，由 Anthropic 于 2024 年发布",
    ]
    for f in new_findings:
        print(f"  新发现：{f}")

    # ── 3. 冲突检测 ────────────────────────────────────────
    print("\n── 步骤3：check_conflicts 检测冲突 ──────────────")
    llm = MockConflictLLM()
    result = nodes.check_conflicts(new_findings, store, llm)
    print(f"  检测到冲突：{len(result['conflicts'])} 个")
    for c in result["conflicts"]:
        print(f"    ⚡ {c}")
    print(f"  生成补研问题：{len(result['queries'])} 个")
    for q in result["queries"]:
        print(f"    ❓ {q}")

    # ── 4. 双通道路由 ──────────────────────────────────────
    print("\n── 步骤4：双通道路由 ─────────────────────────────")
    config.settings.__dict__["max_re_research"] = 2
    config.settings.__dict__["max_rewrites"] = 3

    # 模拟 reviewer 的决策
    if result["conflicts"]:
        print(f"  reviewer 判定：re_research（事实冲突，优先修正认知）")
        print(f"  review_route → research_team（用补研问题做子题）")
        print(f"  补研问题：{result['queries']}")
    else:
        print(f"  无冲突，走文字通道")

    # 演示路由函数
    from langgraph.graph import END
    route = nodes.review_route({
        "review_decision": "re_research",
        "rewrite_count": 0,
        "re_research_count": 1,
        "messages": [], "findings": [], "research_summary": "",
        "report": "", "feedback": "",
        "conflicts": result["conflicts"],
        "re_research_queries": result["queries"],
    })
    print(f"  review_route 返回：{route}")
    assert route == "research_team", "冲突时应路由到 research_team"
    print(f"  ✅ 正确路由到 research_team（定向补研）")

    # ── 5. 修正说明 ────────────────────────────────────────
    print("\n── 步骤5：writer 的修正说明 ─────────────────────")
    print("  补研完成后，writer 在报告中写修正说明：")
    print("    【修正说明】")
    print(f"    旧结论：{old_mem.conclusion}")
    print(f"    新证据：MCP 协议基于 JSON-RPC 2.0（官方文档证实）")
    print(f"    采信新的：旧结论是早期未证实的推测，新发现有官方文档支撑")
    print(f"    → Agent 不只改错字，还改了错误认知")

    # 清理
    shutil.rmtree(demo_dir, ignore_errors=True)
    config.settings.__dict__["enable_memory"] = False
    nodes._memory_store = None

    print("\n" + "=" * 60)
    print("✅ 双通道 reviewer：文字差→重写，事实冲突→定向补研→修正说明")
    print("=" * 60)


if __name__ == "__main__":
    main()
