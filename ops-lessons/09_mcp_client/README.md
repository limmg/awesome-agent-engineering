# Lesson 09 — Agent 作为 MCP Client：两个作品串起来

> 本课目标：**让 research-assistant（Agent 项目）作为 MCP client 调用 L08 的 kb-qa 知识库 server，实现「研究助手在研究时能查内部知识库」——把仓库里两个生产级作品通过标准协议连成一个系统**。
>
> 学完你能回答面试官那句：**「你的几个项目能协同吗？」**——不是各自独立的 demo，而是通过 MCP 标准协议打通、能互调的系统。

---

## 1. 为什么要打通两个作品？

仓库里有两个生产级项目，但一直是「各跑各的」：

| 项目 | 能力 | 局限 |
|---|---|---|
| **research-assistant**（Agent） | 联网搜索 + 多研究员并行 + 审稿 | 只能查**外部**信息，不知道公司内部制度 |
| **kb-qa**（RAG） | 企业知识库检索 + 生成 | 只能查**内部**文档，不会自主研究 |

现实的研究场景往往要**两者结合**：「调研某竞品，结合我们公司的产品资料做对比」。打通后，research-assistant 研究时能先查内部知识库（公司有什么相关资料）、再联网补充外部信息——一个研究流程同时用到内部+外部数据源。

> 🎯 **核心价值**：这不是「又写一个 demo」，而是证明两个已有作品能**通过标准协议互操作**。这正是 MCP 的终极意义——M+N 集成里，这俩项目就是 M 和 N 的实例：Agent 是 host(M 侧)，kb-qa 是 server(N 侧)，标准协议让它们零适配对接。

```
   打通前：两个孤岛
   research-assistant ──联网──▶ 外部信息
   kb-qa              ──检索──▶ 内部文档
        （互不相干）

   打通后：一个研究系统
   research-assistant（Agent / MCP host）
        ├─ 联网搜索 web_search ──▶ 外部信息
        └─ 内部知识库 kb_search ──▶ MCP ──▶ kb-qa server ──▶ 内部文档
        （先查内部有什么，再联网补充）
```

---

## 2. MCP client 怎么接入 Agent？

L07 学了 client 怎么调 server（list_tools + call_tool）。本课的问题是：**怎么把这套调用变成 Agent 的一个「工具」**。

research-assistant 的工具模式是「**异步函数返回格式化文本**」（见 `tools.py` 的 `web_search`），节点里直接 `await web_search(subtopic)` 调用。所以接入 MCP 工具，就是写一个**同样签名的 `kb_search` 函数，内部走 MCP client 协议调 kb-qa**：

```python
async def kb_search(query: str) -> str:
    """查内部知识库（通过 MCP 协议调 kb-qa server）。"""
    # 1. 用 stdio_client 拉起 kb-qa 的 mcp_server 子进程
    # 2. ClientSession → call_tool("search_knowledge_base", {query})
    # 3. 把返回的结构化材料格式化成文本（和 web_search 同格式）
```

> 💡 **关键设计**：对 Agent 来说，`kb_search` 和 `web_search` 长得一模一样（都是 `async def f(query) -> str`）。Agent 不关心一个是联网、一个是走 MCP——**协议的标准化让工具来源对调用方透明**。这就是 MCP 的解耦价值：加一个远程工具，Agent 代码风格零变化。

### 连接管理：长连接 vs 按需拉起

MCP client 调用 server 有两种连接策略：

| 策略 | 怎么做 | 适合 | 本课 |
|---|---|---|---|
| **按需拉起** | 每次 kb_search 拉起 server 子进程、用完关掉 | 工具偶尔用、教学清晰 | ✅ 用这个（最简单可跑） |
| **长连接** | Agent 启动时建一次连接，复用到关闭 | 工具高频用、生产 | 进阶（见 exercise） |

按需拉起每次有进程启动开销（~1s），但逻辑最清晰、不需要管连接生命周期。生产高频场景应换长连接（建一次会话，多次 call_tool 复用）。

---

## 3. 「先内部后外部」的研究策略

打通后，researcher 节点的检索策略从「只联网」升级为「**先查内部知识库，再联网补充**」：

```
   打通前的 researcher：
      subtopic ──web_search──▶ 外部素材 ──▶ LLM 综合 ──▶ finding

   打通后的 researcher：
      subtopic ──┬─kb_search(MCP)──▶ 内部材料 ─┐
                 └─web_search─────▶ 外部素材 ─┤──合并──▶ LLM 综合 ──▶ finding
                                              │
                                  内部+外部双源，更全面
```

为什么「先内部」？因为内部知识库是**权威可信**的（公司制度、产品资料是确定的），联网结果需要甄别。研究时优先采信内部数据，外部只作补充验证。

> 🎯 **这是 Agent 工具集从「本地函数」扩展到「远程 MCP 工具」的实质意义**：Agent 的能力边界从「本进程的几个函数」扩大到「整个 MCP 生态的任意 server」。research-assistant 现在能调的不止 web_search，还有任意被封装成 MCP server 的企业系统。

---

## 4. 多 server 编排的雏形

本课是「单 MCP server」接入（只接 kb-qa）。但 MCP 的设计天然支持**多 server 编排**——一个 host 同时连多个 server，每个 server 是一个工具源：

```
   research-assistant（host）
      ├─ 本地工具：web_search（联网）
      ├─ MCP server A：kb-qa（内部知识库）
      ├─ MCP server B：CRM（客户数据）        ← 未来可扩
      └─ MCP server C：数据分析（报表查询）   ← 未来可扩
```

每个 server 独立发现、独立调用，host 像拼积木一样组合。这就是 M+N 的 M 侧——加一个工具源 = 多连一个 server，不影响其他。

---

## 5. 本课代码会做什么

### 落地到 research-assistant
- 新增 `src/research_assistant/kb_mcp_client.py`：`kb_search(query)` 函数，作为 MCP client 调 L08 的 kb-qa server（按需拉起 + 格式化返回）
- `config.py`：加 `kb_mcp_server_path`（指向 kb-qa 的 mcp_server.py）+ `enable_kb_search` 开关（默认关，无 kb-qa 时降级）
- `nodes.py`：researcher 节点在 `web_search` 之外，可选先调 `kb_search`，合并内部+外部素材
- 配置 + 降级：kb-qa 不可用时 `kb_search` 优雅返回空，researcher 仍能纯联网跑（不破坏现有功能）

### 教学演示
`ops-lessons/09_mcp_client/` 放 README + 一个验证 kb_search 能调通 kb-qa 的演示脚本。

---

## 6. 跑起来

### 验证 MCP client 工具

```bash
cd portfolio-projects/research-assistant
# 前提：kb-qa 已入库 + 两个项目都配了 ZHIPUAI_API_KEY
python -c "
import asyncio, sys
sys.path.insert(0,'src')
from research_assistant.kb_mcp_client import kb_search
print(asyncio.run(kb_search('云帆科技试用期多久')))
"
```

预期：返回 kb-qa 检索到的内部材料（格式化文本，带来源）。

### 跑完整研究（内部+外部双源）

```bash
python cli.py "云帆科技的试用期政策和行业惯例对比"
# → researcher 会先查内部知识库（试用期政策）+ 联网（行业惯例），合并综合
```

---

## 🎯 面试话术

> 「我的两个项目通过 MCP 打通了：research-assistant 作为 MCP client，研究时能调用 kb-qa 的 `search_knowledge_base` 工具查内部知识库，再联网补充外部信息——一个研究流程同时用内部+外部数据源。这展示了标准协议下的系统集成：Agent 工具集从『本地函数』扩展到『远程 MCP 工具』，加一个工具源就是多连一个 server，Agent 代码风格零变化。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/research_assistant/kb_mcp_client.py` | **新增**：`kb_search` MCP client 函数，调 kb-qa server | `python -c "...kb_search('试用期')"` |
| `src/research_assistant/config.py` | 加 `kb_mcp_server_path` / `enable_kb_search` | — |
| `src/research_assistant/nodes.py` | researcher 节点可选先调 `kb_search`，合并内部+外部 | 跑 `cli.py` 看 finding 含内部来源 |
| `ops-lessons/09_mcp_client/demo.py` | 演示脚本：验证 kb_search 调通 kb-qa | `python demo.py` |

下一课 [Lesson 10 — 语义缓存](../10_semantic_cache/) 进入性能与成本模块。
