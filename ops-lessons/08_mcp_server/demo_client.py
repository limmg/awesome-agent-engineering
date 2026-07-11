"""L08 演示 client：调用 kb-qa 的 MCP server，验证 search_knowledge_base 可用。

把 kb-qa 的 mcp_server.py 当子进程拉起（stdio），发现工具并调用。
需要：kb-qa 已入库（python cli.py ingest）+ ZHIPUAI_API_KEY 配置。
未入库时会报「知识库为空」——这是预期行为（提示先 ingest）。

运行（从 ops-lessons/08_mcp_server/ 下）：
    python demo_client.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# kb-qa mcp_server.py 的绝对路径
KB_QA_ROOT = Path(__file__).resolve().parents[2] / "portfolio-projects" / "knowledge-base-qa"
MCP_SERVER = KB_QA_ROOT / "mcp_server.py"


async def run() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER)],  # 默认 stdio 模式
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    print(f"→ 拉起 kb-qa MCP server（{MCP_SERVER.name}）…\n")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ 连接成功\n")

            tools = (await session.list_tools()).tools
            print(f"📋 发现 {len(tools)} 个工具：")
            for t in tools:
                print(f"   - {t.name}")
            print()

            query = "云帆科技试用期多久"
            print(f"🔧 调用 search_knowledge_base(query='{query}'):")
            result = await session.call_tool("search_knowledge_base", {"query": query})
            print(f"   ← {result.content[0].text[:300]}\n")

            print("💡 server 工作正常。把上面这段注册进 Claude Desktop 配置即可即插即用。")


if __name__ == "__main__":
    if not MCP_SERVER.exists():
        print(f"❌ 找不到 {MCP_SERVER}，请确认 kb-qa 项目位置")
        sys.exit(1)
    asyncio.run(run())
