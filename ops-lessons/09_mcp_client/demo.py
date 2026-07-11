"""L09 演示：research-assistant 作为 MCP client 调用 kb-qa 知识库。

验证 kb_search 工具能经 MCP 协议查到 kb-qa 的内部材料。
前提：kb-qa 已入库（portfolio-projects/knowledge-base-qa/ 下 python cli.py ingest）
      + 两个项目共享 ZHIPUAI_API_KEY（读仓库根 .env）。

运行（从本目录）：
    python demo.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 把 research-assistant 的 src 加入路径
RA_SRC = Path(__file__).resolve().parents[2] / "portfolio-projects" / "research-assistant" / "src"
sys.path.insert(0, str(RA_SRC))


async def main() -> None:
    from research_assistant.config import settings
    from research_assistant.kb_mcp_client import kb_search

    # 临时启用 kb_search（默认关，演示时打开）
    settings.enable_kb_search = True

    print("=" * 64)
    print("演示：research-assistant 经 MCP 调用 kb-qa 内部知识库")
    print("=" * 64)
    query = "云帆科技试用期多久"
    print(f"\n🔍 kb_search('{query}'):\n")
    result = await kb_search(query)
    print(result)
    print("\n" + "=" * 64)
    print("💡 这就是两个项目打通的证据：research-assistant 通过 MCP 协议")
    print("   拿到了 kb-qa 的内部材料，和 web_search 一样是 Agent 的一个工具。")


if __name__ == "__main__":
    asyncio.run(main())
