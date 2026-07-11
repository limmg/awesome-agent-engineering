"""MCP client 工具：让 research-assistant 通过 MCP 协议查 kb-qa 内部知识库（LLMOps L09）。

把 L08 的 kb-qa MCP server 作为一个研究工具接入 Agent。
对 Agent 来说，kb_search 和 web_search 签名一致（async def f(query)->str），
来源透明——这就是 MCP 标准化的解耦价值。

设计：
    - 按需拉起：每次 kb_search 用 stdio_client 拉起 kb-qa mcp_server 子进程，
      用完关闭（逻辑最清晰；高频场景应换长连接，见 exercise）
    - 优雅降级：kb-qa 不可用（路径错/未入库/key 缺）时返回友好提示，
      researcher 仍能纯联网跑（不破坏现有功能）
    - 格式对齐 web_search：返回「[序号] 出处 / 内容 / 来源」文本，便于 LLM 合并
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .config import settings


def _kb_mcp_server_path() -> Path:
    """kb-qa mcp_server.py 的路径。

    默认指向同仓库的 portfolio-projects/knowledge-base-qa/mcp_server.py，
    也可用 KB_MCP_SERVER_PATH 环境变量覆盖。
    """
    if settings.kb_mcp_server_path:
        return Path(settings.kb_mcp_server_path)
    # research-assistant/src/research_assistant/ → 上溯到 portfolio-projects/
    # here 是 research_assistant 目录，parents[2] = portfolio-projects
    here = Path(__file__).resolve().parent
    return here.parents[2] / "knowledge-base-qa" / "mcp_server.py"


async def kb_search(query: str) -> str:
    """通过 MCP 协议查询 kb-qa 内部知识库，返回格式化材料文本。

    和 web_search 同签名（async def f(query) -> str），对 Agent 透明。
    失败时返回友好提示（不抛异常），让 researcher 能降级为纯联网。

    Args:
        query: 查询问题

    Returns:
        格式化文本：每条 [序号] 出处 · 章节 / 内容；失败返回降级提示。
    """
    if not settings.enable_kb_search:
        return f"内部知识库查询未启用（enable_kb_search=false）。"

    server_path = _kb_mcp_server_path()
    if not server_path.exists():
        return f"内部知识库 MCP server 未找到（{server_path}），跳过内部检索。"

    try:
        # 延迟导入：mcp 是 research-assistant 的可选依赖（无 mcp 包时降级）
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return "内部知识库 MCP client 不可用（未安装 mcp 包），跳过内部检索。"

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
        env={**dict(__import__("os").environ), "PYTHONIOENCODING": "utf-8"},
    )

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "search_knowledge_base", {"query": query}
                )
                raw = result.content[0].text if result.content else "[]"
                return _format_kb_results(raw, query)
    except Exception as e:
        return (f"内部知识库查询失败（{type(e).__name__}: {e}）。"
                f"可能是未入库或 key 缺失，已降级为纯联网。")


def _format_kb_results(raw_json: str, query: str) -> str:
    """把 kb-qa 返回的结构化材料格式化成和 web_search 风格一致的文本。"""
    try:
        docs = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return f"内部知识库 '{query}' 返回格式异常。"
    if not docs:
        return f"内部知识库 '{query}' 没有相关材料。"

    lines = [f"内部知识库检索 '{query}'，命中 {len(docs)} 条："]
    for d in docs:
        src = d.get("source", "未知来源")
        section = d.get("section", "")
        content = (d.get("content") or "")[:150]
        loc = f"{src} · {section}" if section else src
        lines.append(f"[内部] {loc}\n    {content}\n    来源: 企业知识库（{src}）")
    return "\n".join(lines)
