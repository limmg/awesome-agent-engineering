# Lesson 07 — MCP 是什么：AI 应用的「USB 接口」

> 本课目标：**理解 MCP（Model Context Protocol）协议的定位与价值——让工具/数据源以标准协议被任意 LLM host 调用，解决「每个工具都要为每个 host 重写一遍」的集成地狱**。
>
> 学完你能回答面试官那句：**「了解 MCP 吗？它解决什么问题？」**——这是 2026 年 AI 后端 JD 高频词，本模块补齐这个空白。本课纯教学，手写最小 server/client 跑通 stdio 调用。

---

## 1. MCP 解决什么问题？M×N 集成地狱

假设你有 3 个 LLM host（Claude Desktop、Cursor、自研 Agent），要接 4 个工具（知识库、GitHub、数据库、文件系统）。没有 MCP 的世界长这样：

```
   没有 MCP：M × N 集成
   ─────────────────────────
   3 个 host × 4 个工具 = 12 套适配代码

   Claude ──┬── 知识库适配A
            ├── GitHub适配A
            ├── 数据库适配A
            └── 文件系统适配A
   Cursor ──┬── 知识库适配B     ... 每加一个 host 或工具，
            └── ...              全都要重写一遍适配

   → M×N 套代码，爆炸式增长
```

加一个 host 要给每个工具写适配；加一个工具要给每个 host 写适配。这是典型的 **M×N 问题**。

MCP 把它变成 **M+N**：

```
   有 MCP：M + N 集成
   ─────────────────────────
   每个工具实现一次 MCP Server（暴露标准协议）
   每个 host 实现一次 MCP Client（消费标准协议）

   Claude ──┐
   Cursor ──┼── 【MCP 标准协议】 ──┬── 知识库Server
   Agent ───┘                      ├── GitHub Server
                                   ├── 数据库 Server
                                   └── 文件系统 Server

   3 host + 4 工具 = 7 套代码（不是 12）
   加 host / 加工具 都是 +1，互不影响
```

> 🎯 **核心认知**：MCP 之于 AI 工具 = USB 之于硬件设备。USB 出现前，键盘鼠标打印机各用各的接口；USB 出现后，设备做一次 USB 接口、电脑做一次 USB 口，即插即用。MCP 让「工具接 AI」也变成即插即用——**这是它最值钱的一句话定位**。

| | 没有 MCP | 有 MCP |
|---|---|---|
| 加一个工具 | 给每个 host 写 N 套适配 | 写 1 个 MCP server |
| 加一个 host | 给每个工具写 M 套适配 | 写 1 个 MCP client（很多 host 已内置） |
| 复杂度 | M × N | M + N |

---

## 2. MCP 是什么？（一句话 + 三个身份）

**MCP（Model Context Protocol）** = Anthropic 2024 年底开源的协议，让 LLM 应用与外部工具/数据源标准化通信。

它的三层身份：

| 身份 | 说明 |
|---|---|
| **协议** | 定义了 host 和 server 之间「怎么发现工具、怎么调用、返回什么格式」的规范 |
| **SDK** | 官方提供 Python/TypeScript SDK，几行代码就能写 server/client |
| **生态** | 已有大量现成 server（GitHub、Slack、数据库…），host 也广泛支持（Claude Desktop/Code、Cursor、IDE） |

> 💡 类比：MCP 协议像 HTTP，SDK 像 requests/axios，生态像「网上有无数网站」。你写 server = 建一个网站，写 client = 写个浏览器。

---

## 3. 核心概念：tools / resources / prompts

MCP server 能暴露三种能力：

| 能力 | 是什么 | 谁触发 | 例子 |
|---|---|---|---|
| **tools** 🛠️ | 可执行的函数（有副作用） | LLM 决定调用 | `search_kb(query)` 查知识库、`send_email(to,body)` 发邮件 |
| **resources** 📄 | 可读取的数据（只读，无副作用） | host/用户选择读取 | `file:///config.json`、`db://schema` |
| **prompts** 💬 | 预定义的 prompt 模板 | 用户主动选用 | 「代码审查模板」「总结文档模板」 |

> 🎯 **本课聚焦 tools**——它是最高频、最实用的能力（L08 把 kb-qa 封成 tool）。resources/prompts 了解即可。
>
> **tools vs resources 的关键区别**：tools 有副作用（会改变状态，如发邮件/写库），resources 只读。LLM 自主决定调 tool；resource 通常由用户/host 主动选取。这个区分让 host 能合理控制「什么操作需要人确认」。

---

## 4. client-server 架构与传输方式

MCP 是 client-server 架构：

```
   ┌─────────┐  MCP 协议   ┌─────────┐
   │  Host   │◄───────────►│ Server  │
   │ (含     │  (JSON-RPC) │ (工具    │
   │ Client) │             │  实现)   │
   └─────────┘             └─────────┘
       │                        │
   Claude/IDE/Agent         知识库/GitHub/DB
```

- **Host**：运行 LLM 的应用（Claude Desktop、Cursor…），内含 MCP Client
- **Server**：工具/数据源的封装，实现 MCP 协议，被 client 调用
- **通信协议**：基于 JSON-RPC 2.0（请求-响应模式）

### 三种传输方式（Transport）

| 传输 | 怎么连 | 适合 | 本课 |
|---|---|---|---|
| **stdio** | 子进程，通过标准输入/输出通信 | 本地工具（同一台机器） | ✅ 用这个 |
| **SSE** | HTTP + Server-Sent Events | 早期远程方案 | 了解 |
| **Streamable HTTP** | HTTP 流式（新标准） | 远程/生产部署 | L08 会提 |

> 💡 **stdio 最简单**：client 把 server 当子进程拉起，通过 stdin/stdout 收发 JSON-RPC 消息。本地开发/教学首选，无需起 HTTP 服务。生产跨机器才用 HTTP 传输。

```
stdio 传输的数据流：
   Client (父进程)                    Server (子进程)
        │ ──stdin──▶ 写 JSON-RPC 请求 ──▶│
        │ ◀─stdout─ 读 JSON-RPC 响应 ────│
        │ ◀─stderr── server 的日志 ──────│
```

---

## 5. MCP vs Function Calling：不是替代是分层

很多人混淆这两个。它们是**不同层次**的东西，配合使用：

| | Function Calling | MCP |
|---|---|---|
| **是什么** | LLM 的能力：模型能输出结构化的「我要调哪个函数+参数」 | 协议：标准化工具的暴露和调用方式 |
| **层次** | 模型层（LLM 内部） | 传输层（host 和工具之间） |
| **解决的问题** | 让 LLM 会「说」要调什么 | 让工具能被「标准化地接」给任意 host |
| **关系** | LLM 用 function calling 决定调啥 → host 通过 MCP 协议去调 | |

```
   用户："查下试用期多久"
        │
   LLM（用 function calling 决定）："我要调 search_kb(query='试用期')"
        │
   Host（通过 MCP 协议）──stdio/HTTP──▶ KB MCP Server
        │                                     │
        │ ◀── 返回结构化结果 ──────────────────│
        │
   LLM 用结果生成最终回答
```

> 🎯 **一句话**：Function Calling 是「LLM 会点菜」，MCP 是「餐厅用统一菜单格式接单」。LLM 点什么菜（function calling）和菜怎么标准化上桌（MCP）是两件事。有了 MCP，你换一个支持 MCP 的 host，工具零改动就能用。

---

## 6. 一次完整的 MCP 调用流程

client 连上 server 后，标准流程是「发现 → 调用」：

```
   1. 连接：Client 通过 stdio/HTTP 拉起并连上 Server
   2. 握手：双方交换协议版本、能力（server 声明有哪些 tools）
   3. 发现：Client 调 list_tools() → 拿到工具清单（名字/描述/参数schema）
   4. 调用：Client 调 call_tool(name, args) → Server 执行 → 返回结果
   5. 关闭：用完关闭连接
```

第 3 步是 MCP 的精髓——**动态发现**。Client 不需要预先硬编码「server 有哪些工具」，而是运行时问 server「你有什么」。这意味着新加工具只改 server，client/host 自动发现，零改动。

> 💡 这正是 L09 的基础：research-assistant 作为 client，连上 kb-qa 的 MCP server 后，自动发现 `search_knowledge_base` 工具并接入，不用改 agent 代码。

---

## 7. 本课代码会做什么

`code.py` 用官方 Python SDK（`pip install mcp`，已装）写：

1. **最小 MCP Server**：暴露两个 tool（`echo` 回显、`add` 加法），用 FastMCP + `@mcp.tool()` 装饰器
2. **最小 MCP Client**：用 `stdio_client` + `ClientSession`，连上 server → `list_tools()` 发现 → `call_tool()` 调用 echo 和 add
3. 跑通 stdio 传输，控制台看到完整的「发现 + 调用」往返

> 这是**真实可运行**的 MCP（不是 mock）——mcp 1.26.0 已装。client 会真的把 server 当子进程拉起、走 JSON-RPC 通信。

---

## 8. 跑起来

```bash
cd ops-lessons/07_mcp_basics
python code.py
```

预期：控制台打印 client 发现的两个工具（echo / add），并显示调用 echo 和 add 的结果，证明 stdio 通信跑通。

> ⚠️ Windows 注意：stdio 传输会拉起子进程，首次运行可能稍慢（启动 Python 解释器）。若报编码错，设 `PYTHONIOENCODING=utf-8`。

---

## 🎯 面试话术

> 「MCP 是 Anthropic 开源的协议，解决 AI 工具集成的 M×N 问题——以前 N 个工具要给 M 个 host 各写适配，MCP 把它变成 M+N：工具实现一次 MCP server、host 实现一次 client，即插即用，就像 USB 之于硬件。它暴露 tools/resources/prompts 三种能力，client 动态发现 server 的工具清单。和 Function Calling 不冲突——LLM 用 function calling 决定调啥，host 通过 MCP 协议去调。我手写过最小 server/client 跑通 stdio 传输。」

---

## 落地清单

本课纯教学，无 kb-qa 改动。

| 文件 | 内容 |
|---|---|
| `code.py` | 最小 FastMCP server（echo/add 两个 tool）+ stdio client（list_tools + call_tool） |

下一课 [Lesson 08 — 把知识库封成 MCP Server](../08_mcp_server/) 把 kb-qa 的检索能力变成 MCP tool。
