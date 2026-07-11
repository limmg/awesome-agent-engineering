"""MCP Server：把企业知识库检索能力暴露为标准 MCP 工具（LLMOps L08）。

把 kb-qa 的 KBRetriever 包装成两个 MCP tool，让任意 MCP host
（Claude Desktop/Code、Cursor、自研 Agent）即插即用地查企业知识库：
    search_knowledge_base(query, mode) —— 只检索，返回带出处的材料
    ask_knowledge_base(question)        —— 检索 + 生成完整答案

这是 kb-qa 从「一个 Web 服务」升级成「一个标准工具」的关键：
host 配一行 JSON 就能调用，不用写适配代码（M+N 集成的 N 侧）。

用法（项目根下）：
    python mcp_server.py                  # stdio 模式（Claude Desktop 默认）
    python mcp_server.py --transport http # streamable HTTP 模式（远程/多host）

依赖：mcp>=1.0（已装）。前提：已入库（python cli.py ingest）+ ZHIPUAI_API_KEY。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# ── 路径 setup（同 cli.py：让 src 可 import，Windows 控制台 utf-8）─────────
_ROOT = Path(__file__).resolve().parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from kb_qa.retriever import KBRetriever  # noqa: E402

# 压低 FastMCP 的请求级 INFO 日志（ListToolsRequest 等会刷屏）
logging.getLogger("mcp").setLevel(logging.WARNING)

# ── KB 单例：BM25 索引构建有成本，建一次答多次（同 service.py 的 get_kb）──
_kb: KBRetriever | None = None
_kb_lock = asyncio.Lock()


async def get_kb() -> KBRetriever:
    global _kb
    async with _kb_lock:
        if _kb is None:
            _kb = await asyncio.to_thread(KBRetriever)
        return _kb


# ════════════════════════════════════════════════════════════════
# MCP Server 定义
# ════════════════════════════════════════════════════════════════
mcp = FastMCP(
    "kb-qa",
    instructions=(
        "企业知识库问答 MCP server。提供知识库检索（search_knowledge_base）"
        "和完整问答（ask_knowledge_base）两个工具，用于回答公司制度、流程、"
        "产品等内部文档相关问题。检索结果带文档出处。"
    ),
)


@mcp.tool()
async def search_knowledge_base(query: str, mode: str = "rerank") -> str:
    """查询企业知识库，返回与问题最相关的材料片段（带文档出处）。

    适用于回答公司制度、流程、产品、人事政策等内部文档相关的问题。
    返回多条材料，每条含来源文档和章节，可用于引用溯源。
    当用户问的是公司内部信息时，应优先用此工具而非凭记忆回答。

    Args:
        query: 用户的自然语言问题（中英文均可）
        mode: 检索模式，rerank（混合+重排，默认最优）/ hybrid（混合）/ vector（纯向量）
    """
    kb = await get_kb()
    # KBRetriever.retrieve 是同步的（BM25/jieba），用 to_thread 丢线程池不阻塞事件循环
    docs = await asyncio.to_thread(kb.retrieve, query, mode)
    results = [
        {
            "idx": i,
            "source": d.metadata.get("source", "未知来源"),
            "section": d.metadata.get("section", ""),
            "content": d.page_content,
        }
        for i, d in enumerate(docs, 1)
    ]
    return json.dumps(results, ensure_ascii=False)


@mcp.tool()
async def ask_knowledge_base(question: str) -> str:
    """对企业知识库提问，返回基于检索材料的完整答案（带引用标注）。

    与 search_knowledge_base 的区别：这个工具会直接生成最终答案（检索+生成），
    适合「我只想要个答案」的简单查询。如果需要自己组织答案或结合多源信息，
    用 search_knowledge_base 拿原始材料更合适。

    Args:
        question: 用户的问题
    """
    # 复用 kb-qa 的检索+生成管线
    from kb_qa.generate import stream_answer

    kb = await get_kb()
    docs = await asyncio.to_thread(kb.retrieve, question)
    answer_parts = [tok async for tok in stream_answer(question, docs)]
    return "".join(answer_parts)


# ════════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(description="kb-qa MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="传输方式：stdio（本地/Claude Desktop默认）或 http（远程/多host）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 模式监听地址")
    parser.add_argument("--port", type=int, default=8002, help="HTTP 模式监听端口")
    args = parser.parse_args()

    if args.transport == "stdio":
        # stdio：host 拉起本进程作子进程，通过 stdin/stdout 收发 JSON-RPC
        mcp.run(transport="stdio")
    else:
        # streamable HTTP：常驻服务，多 host 共享，BM25 索引建一次
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(f"kb-qa MCP server (HTTP) 监听 http://{args.host}:{args.port}/mcp")
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
