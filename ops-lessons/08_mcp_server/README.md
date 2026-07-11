# Lesson 08 — 把知识库封成 MCP Server

> 本课目标：**把 kb-qa 的检索能力包装成 MCP server，暴露 `search_knowledge_base` 工具，让任意 MCP host（Claude Desktop/Code、Cursor、自研 Agent）直接查你的企业知识库，工具零改动接入**。
>
> 学完你能回答面试官那句：**「你的知识库怎么被别的系统集成？」**——不是写 API 让对方对接，而是封成标准 MCP 工具，任何支持 MCP 的 host 即插即用。

---

## 1. 为什么把 RAG 封成 MCP？（回顾 L07 的 M+N）

kb-qa 已经有 HTTP API（`/api/ask`）。那为什么还要封 MCP？两个场景对比：

| 集成方式 | 接 Claude Desktop | 接 Cursor | 接自研 Agent |
|---|---|---|---|
| **HTTP API** | 写适配代码调 `/api/ask` 解析 SSE | 再写一套适配 | 再写一套 |
| **MCP Server** | 配置文件一行（Claude 内置 MCP client） | 配置文件一行 | 标准 client 调用 |

```
   没有 MCP：每接一个 host，写一套「调 HTTP + 解析 SSE + 转成 host 能用的格式」
   有 MCP  ：封一次 server，所有 host 用同一个标准协议调用
```

> 🎯 **核心价值**：把 RAG 从「一个 Web 服务」升级成「一个标准工具」。Web 服务要 host 写适配；标准工具是即插即用。这是 kb-qa 从「能被 curl 调」到「能被整个 AI 生态调」的跃迁。

---

## 2. 如何把业务能力映射成 MCP tool？

把 `KBRetriever.retrieve` 封成 MCP tool，要设计三样东西：

### ① 入参 schema（tool 的参数）
```python
search_knowledge_base(query: str, mode: str = "rerank") -> ...
```
- `query`：用户的问题（必填）
- `mode`：检索模式（可选，默认 rerank —— 复用 kb-qa 的最优管线）

### ② 返回结构（要带出处）
MCP tool 返回的是给 LLM 看的内容。RAG 检索的结果必须**带 source**，否则 LLM 编不出引用：

```json
[
  {"idx": 1, "source": "employee_handbook.md", "section": "试用期",
   "content": "试用期 3 个月，转正工资 100%。"},
  ...
]
```

### ③ 工具描述（给 LLM 看的「使用说明」）
描述决定 LLM 会不会正确选用这个工具。要写清「**查什么 / 返回什么 / 什么时候用**」：

```python
"""查询企业知识库，返回与问题最相关的材料片段（带文档出处）。
适用于回答公司制度、流程、产品等内部文档相关的问题。
返回多条材料，每条含来源文档和章节，可用于引用溯源。"""
```

> 💡 **工具描述是 MCP 工程化的关键**（L07 练习 2 讲过）。描述写得好，LLM 才会在「用户问公司制度」时主动调它、在「用户聊天气」时不乱调。这是把 RAG 接入 Agent 后能否真正被用起来的决定因素。

---

## 3. 两个工具：检索 vs 完整问答

本课封两个工具，对应两个粒度：

| 工具 | 做什么 | 给谁用 | 适合场景 |
|---|---|---|---|
| **`search_knowledge_base`** | 只检索，返回材料（不生成） | 让调用方/host 的 LLM 自己组织答案 | Agent 集成（材料作为工具结果，Agent 决定怎么用） |
| **`ask_knowledge_base`** | 检索 + 生成完整答案（复用 kb-qa 管线） | 直接拿答案 | 简单查询、不想自己拼 prompt 的 host |

```
search（轻）：query → [材料1, 材料2, ...]   ← 把判断权交给 host 的 LLM
ask（重）  ：query → "试用期 3 个月..."      ← kb-qa 自己生成好答案
```

> 🎯 **为什么默认推 search 而非 ask？** 因为 L09 的 Agent 集成场景下，Agent 拿到材料后还要结合联网结果综合判断——它要的是「原料」不是「成品」。`ask` 适合「我只想要个答案」的简单 host。**给工具的使用者留决策空间**，是好 API 设计的通用原则。

---

## 4. stdio vs HTTP 部署：选哪个？

| | stdio | Streamable HTTP |
|---|---|---|
| **怎么起** | host 拉起 server 子进程 | server 常驻，host 连 URL |
| **适合** | 本地工具（Claude Desktop 配置） | 远程/多 host 共享/容器化 |
| **本课** | ✅ 默认（最简单，配 Claude Desktop） | 提供 `--transport http` 选项 |

kb-qa 的检索需要建 BM25 索引（有启动成本），stdio 每次拉起都要重建一次索引——本地单用户够用；生产多用户应走 HTTP 常驻。所以 `mcp_server.py` 两种都支持，默认 stdio，加参数切 HTTP。

---

## 5. 同步检索 + MCP 的坑：用 to_thread 包一层

kb-qa 的 `KBRetriever.retrieve` 是**同步**的（BM25/jieba 都是同步库）。但 MCP tool 在 async 上下文跑。直接调会阻塞事件循环。解法：`asyncio.to_thread` 把同步检索丢到线程池：

```python
@mcp.tool()
async def search_knowledge_base(query: str, mode: str = "rerank") -> str:
    docs = await asyncio.to_thread(_kb.retrieve, query, mode)  # 同步→线程池
    return json.dumps([{"idx": i, "content": d.page_content, ...} for ...])
```

> 💡 这是「同步业务代码 + async 框架」的通用适配模式。L01–L06 的 service.py 里已经大量用了 `asyncio.to_thread`（BM25 检索、ingest 都是这么包的）——MCP server 复用同一思路。

---

## 6. 本课代码会做什么

### 落地到 kb-qa：新增 `mcp_server.py`
- 用 FastMCP 暴露 `search_knowledge_base(query, mode)` 和 `ask_knowledge_base(question)` 两个 tool
- 复用现有 config / KBRetriever / generate 管线（不重写检索逻辑）
- 支持 stdio（默认）和 streamable HTTP（`--transport http`）两种传输
- BM25 索引单例化（建一次答多次，避免每次 tool 调用重建）

### 在 Claude Desktop / Claude Code 注册
README 给出 `claude_desktop_config.json` 配置片段，复制即用。

---

## 7. 跑起来

### 验证 server（用 L07 的 client 思路 / inspector）

```bash
cd portfolio-projects/knowledge-base-qa
# 前提：已入库（python cli.py ingest）+ 配了 ZHIPUAI_API_KEY
# 方式 1：用 MCP inspector 可视化调试
npx @modelcontextprotocol/inspector python mcp_server.py
# 方式 2：写个一次性 client 调（参考 L07 的 run_client）
python -c "
import asyncio, sys
sys.path.insert(0,'.')
from ops_demo_client import run  # 见下方说明
asyncio.run(run())
"
```

预期：client 能发现 `search_knowledge_base`，对「云帆科技试用期多久」返回带出处的检索材料。

### 注册到 Claude Desktop

编辑 `claude_desktop_config.json`（macOS: `~/Library/Application Support/Claude/`，Windows: `%APPDATA%\Claude\`）：

```json
{
  "mcpServers": {
    "kb-qa": {
      "command": "python",
      "args": ["D:/workspace/RAG-test/portfolio-projects/knowledge-base-qa/mcp_server.py"],
      "env": { "ZHIPUAI_API_KEY": "your-key", "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

重启 Claude Desktop，对话框里问「试用期多久」，Claude 会自动调用 `search_knowledge_base`。

---

## 🎯 面试话术

> 「我把 RAG 检索封成了 MCP server，暴露 `search_knowledge_base` 工具返回带出处的材料，任意 MCP host（Claude Desktop、Cursor、自研 Agent）配一行 JSON 就能调用我的企业知识库，不用改 host 代码。工具描述写清了查什么返回什么，LLM 会正确选用。这把知识库从『一个要对接的 API』升级成『即插即用的标准工具』——接新 host 是 0 代码。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `mcp_server.py` | **新增**：FastMCP server，`search_knowledge_base` + `ask_knowledge_base` 两个 tool，复用 KBRetriever/generate；stdio/HTTP 双传输 | `python mcp_server.py`（stdio 模式待 client 连接） |
| `ops-lessons/08_mcp_server/demo_client.py` | **新增**：一次性 client，调 `search_knowledge_base` 验证 server 可用 | `python demo_client.py` |

下一课 [Lesson 09 — Agent 作为 MCP Client](../09_mcp_client/) 让 research-assistant 调这个 server，两个作品打通。
