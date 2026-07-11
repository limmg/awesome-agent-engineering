"""
Lesson 07 — MCP 是什么：AI 应用的「USB 接口」
================================================
用官方 mcp SDK 写最小的 server + client，跑通 stdio 传输：

  - Server：FastMCP + @mcp.tool() 暴露 echo / add 两个工具
  - Client：stdio_client 拉起 server 子进程 → ClientSession
            → list_tools() 发现 → call_tool() 调用

运行：python code.py
（会以 server 模式拉起自身子进程通信，真实 JSON-RPC 往返）

依赖：mcp>=1.0（已装）。Windows 如报编码错设 PYTHONIOENCODING=utf-8。
"""
from __future__ import annotations

import asyncio
import sys

# Windows GBK 坑：stdio 通信中文会崩
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ════════════════════════════════════════════════════════════════
# 1. Server：用 FastMCP 暴露两个 tool
# ════════════════════════════════════════════════════════════════
def build_server():
    """构造一个最小 MCP server，暴露 echo 和 add 两个工具。"""
    import logging
    from mcp.server.fastmcp import FastMCP

    # 压低 FastMCP 的 INFO 日志（ListToolsRequest/CallToolRequest 会刷屏）
    logging.getLogger("mcp").setLevel(logging.WARNING)

    mcp = FastMCP("lesson07-demo")

    @mcp.tool()
    def echo(text: str) -> str:
        """原样回显输入文本（最小示例工具）。

        Args:
            text: 要回显的文本
        """
        return f"echo: {text}"

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """两个整数相加，返回它们的和。

        Args:
            a: 第一个加数
            b: 第二个加数
        """
        return a + b

    return mcp


# ════════════════════════════════════════════════════════════════
# 2. Client：连 server → 发现工具 → 调用
# ════════════════════════════════════════════════════════════════
async def run_client() -> None:
    """以 stdio 方式拉起 server 子进程，发现并调用工具。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # server 就是「本文件 以 --server 参数运行」——拉起自身做子进程
    server_params = StdioServerParameters(
        command=sys.executable,          # 用当前 Python 解释器
        args=[__file__, "--server"],     # 运行本脚本的 server 模式
        env={"PYTHONIOENCODING": "utf-8"},
    )

    print("→ 启动 MCP client，正在拉起 server 子进程（stdio 传输）…\n")

    # stdio_client 是个 async context manager：进入时拉起子进程
    async with stdio_client(server_params) as (read_stream, write_stream):
        # ClientSession 负责协议握手 + 提供 list_tools/call_tool
        async with ClientSession(read_stream, write_stream) as session:
            # ① 握手（初始化）——交换协议版本和能力
            await session.initialize()
            print("✅ 已连接 server，握手完成\n")

            # ② 发现工具：list_tools 拿到 server 暴露的所有 tool
            tools_resp = await session.list_tools()
            tools = tools_resp.tools
            print(f"📋 发现 {len(tools)} 个工具：")
            for t in tools:
                print(f"   - {t.name}: {t.description or '(无描述)'}")
            print()

            # ③ 调用工具：call_tool(name, arguments)
            print("🔧 调用 echo(text='你好 MCP'):")
            result = await session.call_tool("echo", {"text": "你好 MCP"})
            # 结果是 content 列表（支持多段返回），这里取第一段的 text
            print(f"   ← {result.content[0].text}\n")

            print("🔧 调用 add(a=17, b=25):")
            result = await session.call_tool("add", {"a": 17, "b": 25})
            print(f"   ← {result.content[0].text}\n")

            # ④ 退出 context 自动关闭连接
    print("✅ client 完成，连接已关闭。")
    print("\n💡 这就是 MCP 的完整往返：发现(list_tools) → 调用(call_tool)。")
    print("   L08 会把 kb-qa 的检索封成这样的 tool，L09 让 agent 当 client 调它。")


# ════════════════════════════════════════════════════════════════
# 3. 入口：默认跑 client，--server 跑 server
# ════════════════════════════════════════════════════════════════
def main() -> None:
    if "--server" in sys.argv:
        # server 模式：FastMCP.run() 接管 stdio，监听 client 的 JSON-RPC
        server = build_server()
        server.run(transport="stdio")
    else:
        # client 模式：拉起 server 子进程并跑发现+调用
        asyncio.run(run_client())


if __name__ == "__main__":
    main()
