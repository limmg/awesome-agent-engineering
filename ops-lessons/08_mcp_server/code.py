"""
Lesson 08 — 把知识库封成 MCP Server（自包含教学版）
======================================================
本文件【零外部依赖、零 API、零入库】演示 L08 的核心思想：
    把一个「检索函数」封装成 MCP tool，让任意 MCP host 即插即用。

与生产落地的区别：
    - 生产版 `portfolio-projects/knowledge-base-qa/mcp_server.py`：
      真调 KBRetriever（BM25+向量+rerank），需 ZHIPUAI_API_KEY + 已入库。
    - 本教学版：用一个内存假知识库（几条云帆科技材料）替代真实检索，
      让你无需任何环境就能跑通「封 tool → 发现 → 调用」的完整往返。

三个 L08 要点在本文件都能看到：
    ① 入参 schema：search_knowledge_base(query, mode)
    ② 返回结构带 source/section（RAG 结果必须可溯源）
    ③ 工具描述写清「查什么/返回什么/何时用」（决定 LLM 会不会正确选用）

运行：python code.py
（会以 server 模式拉起自身子进程，走真实 stdio JSON-RPC 往返）
依赖：mcp>=1.2（已装）。Windows 如报编码错设 PYTHONIOENCODING=utf-8。
"""
from __future__ import annotations

import asyncio
import json
import sys

# Windows GBK 坑：stdio 通信中文会崩
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# 0. 假知识库：替代生产版的 KBRetriever（教学用，无需入库/API）
# ════════════════════════════════════════════════════════════════
_FAKE_KB = [
    {"source": "employee_handbook.md", "section": "试用期",
     "content": "云帆科技试用期为 3 个月，试用期工资为转正工资的 100%。"},
    {"source": "employee_handbook.md", "section": "年假",
     "content": "入职满 1 年享 5 天带薪年假，每满 1 年加 1 天，上限 15 天。"},
    {"source": "product_spec.md", "section": "定价",
     "content": "云帆云平台标准版每席位 99 元/月，企业版按需报价。"},
]


def _fake_retrieve(query: str, top_n: int = 2) -> list[dict]:
    """极简「检索」：按查询词与内容的字符重合度打分排序（教学近似）。

    生产版这里是 KBRetriever.retrieve（BM25+向量+rerank）。
    """
    scored = sorted(
        _FAKE_KB,
        key=lambda d: -sum(1 for ch in set(query) if ch in d["content"]),
    )
    return scored[:top_n]


# ════════════════════════════════════════════════════════════════
# 1. Server：把检索封成 search_knowledge_base tool
# ════════════════════════════════════════════════════════════════
def build_server():
    """构造暴露 search_knowledge_base 工具的 MCP server。"""
    import logging
    from mcp.server.fastmcp import FastMCP

    logging.getLogger("mcp").setLevel(logging.WARNING)
    mcp = FastMCP("lesson08-kb-demo")

    @mcp.tool()
    async def search_knowledge_base(query: str, mode: str = "rerank") -> str:
        """查询企业知识库，返回与问题最相关的材料片段（带文档出处）。

        适用于回答公司制度、流程、产品定价等内部文档相关的问题。
        返回多条材料，每条含来源文档和章节，可用于引用溯源。

        Args:
            query: 用户的问题（如「试用期多久」）
            mode: 检索模式（vector/hybrid/rerank，默认 rerank 最优管线）
        """
        # 生产版：docs = await asyncio.to_thread(_kb.retrieve, query, mode)
        # 教学版：直接用假检索（本身很快，无需丢线程池）
        hits = _fake_retrieve(query)
        payload = [
            {"idx": i + 1, "source": h["source"], "section": h["section"],
             "content": h["content"]}
            for i, h in enumerate(hits)
        ]
        return json.dumps(payload, ensure_ascii=False)

    return mcp


# ════════════════════════════════════════════════════════════════
# 2. Client：连 server → 发现 → 调用 search_knowledge_base
# ════════════════════════════════════════════════════════════════
async def run_client() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--server"],      # 拉起自身的 server 模式
        env={"PYTHONIOENCODING": "utf-8"},
    )

    print("→ 启动 MCP client，拉起 kb server 子进程（stdio）…\n")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ 握手完成\n")

            tools = (await session.list_tools()).tools
            print(f"📋 发现 {len(tools)} 个工具：")
            for t in tools:
                print(f"   - {t.name}")
            print()

            query = "云帆科技试用期多久"
            print(f"🔧 调用 search_knowledge_base(query='{query}'):")
            result = await session.call_tool("search_knowledge_base", {"query": query})
            materials = json.loads(result.content[0].text)
            for m in materials:
                print(f"   [材料{m['idx']}] {m['source']}#{m['section']}: {m['content']}")
            print()

    print("💡 这就是 L08 的核心：一个检索函数 → 一个标准 MCP tool。")
    print("   生产版 mcp_server.py 把 _fake_retrieve 换成真实 KBRetriever 即可。")


# ════════════════════════════════════════════════════════════════
# 3. 入口：默认跑 client，--server 跑 server
# ════════════════════════════════════════════════════════════════
def main() -> None:
    if "--server" in sys.argv:
        build_server().run(transport="stdio")
    else:
        asyncio.run(run_client())


if __name__ == "__main__":
    main()
