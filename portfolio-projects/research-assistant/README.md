# 🔬 AI 研究分析助手

> **一句话**：基于 LangGraph 的多智能体并行研究系统——输入研究主题，自动拆解、并行联网检索、智能汇总、审稿迭代，产出带真实来源的结构化研究报告，以流式 API 服务对外提供。

这是 [36 课 LLM 应用实战课程](../../README.md) 的**生产级落地项目**：把课程里学到的 RAG / Agent / 多智能体编排 / 框架工程化能力，缝合成一个**真正可上生产**的 AI 应用。由课程毕业项目 [`workflow-lessons/09_capstone`](../../workflow-lessons/09_capstone/)（教学原型）演进而来，补齐了 8 个生产缺口。

---

## ✨ 核心特性

| 特性 | 说明 | 对应生产缺口 |
|------|------|------|
| 🔍 **真实联网搜索** | DuckDuckGo 检索 + 来源溯源，非 LLM 凭记忆"编" | 替代教学版的幻觉回答 |
| ⚡ **多智能体并行** | N 个 researcher 用 LangGraph `Send` 同时检索不同子问题 | 串行 → 并行，约 2-3× 加速 |
| 🔁 **审稿回路** | reviewer 节点评估报告质量，不合格带反馈回 writer 重写 | 补齐 supervisor 自我迭代逻辑 |
| 🧠 **多模型路由降本** | glm-4-flash 跑并行检索（免费）+ glm-4 跑写作/审稿（质量）| 约 80% 成本节省 |
| 💾 **跨重启持久化** | SqliteSaver 落盘，进程重启后会话记忆不丢 | 替代 InMemorySaver 进程即丢 |
| 📡 **SSE 双层流式** | 进度事件（节点级）+ token 流（逐字输出）同时推送 | 无流式 → 实时反馈 |
| 🌐 **FastAPI 服务化** | REST + SSE，自带前端页面，Docker 一键部署 | 脚本 → 生产服务 |
| 🚦 **并发限流** | Semaphore 控制 web_search QPS，防搜索 API 封禁 | 抗突发流量 |
| 📊 **结构化日志** | 节点进出 + 耗时 + 结果摘要，可接 ELK/Loki | 可观测性 |
| ✅ **25 单元测试** | 不联网、不调真实 LLM、不污染生产 db | 可回归 |

---

## 🏗️ 架构

### 双层图：并行研究子图 + 审稿父图

```
┌─────────────── 并行研究子图（map-reduce）─────────────────┐
│                                                            │
│  START → split ──(Send×N fan-out)──→ researcher ──→ summarize ──→ END
│         (glm-4-flash              (glm-4-flash      (glm-4
│          拆子题)                   +真实搜索          汇总)
│                                   +Semaphore限流)          │
└──────────────────────┬─────────────────────────────────────┘
                       │ 子图作为节点（共享 State 回流）
                       ▼
┌─────────────── 父图（审稿回路 + 持久化）──────────────────┐
│                                                            │
│  START → research_team → writer → reviewer ──(条件)─→ PASS → END
│                          (glm-4)  (glm-4        │
│                                   审质量)        └→ REWORK → writer
│                                                  (rewrite_count++,
│                                                   >=3 强制 PASS)
│                                                            │
│  ⭐ SqliteSaver（Checkpointer）跨轮/跨重启记忆            │
└────────────────────────────────────────────────────────────┘
```

<details>
<summary>Mermaid 源码（可粘贴到 mermaid.live 渲染）</summary>

```mermaid
graph TD
    subgraph 子图["并行研究子图（map-reduce）"]
        S([START]) --> split[split<br/>glm-4-flash 拆子题]
        split -->|"Send×N<br/>并行 fan-out"| R1[researcher 1<br/>真实搜索]
        split --> R2[researcher 2<br/>真实搜索]
        split --> R3[researcher 3<br/>真实搜索]
        R1 --> sum[summarize<br/>glm-4 汇总]
        R2 --> sum
        R3 --> sum
        sum --> SE([END])
    end

    PS([父图 START]) --> RT[research_team<br/>调用子图]
    RT -->|"findings + summary<br/>回流"| W[writer<br/>glm-4 写报告]
    W --> RV[reviewer<br/>glm-4 审稿]
    RV -->|"PASS 或<br/>rewrite_count≥3"| PE([END])
    RV -->|"REWORK<br/>带 feedback"| W

    classDef fast fill:#fef3c7,stroke:#f59e0b
    classDef smart fill:#dbeafe,stroke:#3b82f6
    class split,R1,R2,R3 fast
    class sum,W,RV smart
```
</details>

### 通信机制（三种，对应课程 L05）

- **共享 State**：`findings` 字段 + `operator.add` reducer，子图并行结果自动拼接回流父图
- **消息传递**：`messages` 字段 + `add_messages` reducer，writer 输出经 Checkpointer 跨轮记忆
- **条件路由**：reviewer 通过条件边把 feedback 传回 writer（结构化反馈通道）

---

## 🎯 关键设计决策（面试高频）

### 1. 为什么双层图 + 子图作为节点？

**答**：并行研究是一个内聚的子系统（拆题→并行检索→汇总），封装成子图后，父图只需关心「研究 → 写作 → 审稿」的主流程。子图作为节点嵌入父图（LangGraph 的 `add_node` 接受已编译的图），父图 State 通过共享字段 `findings` 自动接收子图结果。好处：**关注点分离 + 可独立测试子图 + 父图流程清晰**。

### 2. 为什么用 SqliteSaver 而不是 InMemorySaver？

**答**：InMemorySaver 进程退出即丢——开发够用，生产不行。SqliteSaver 把 checkpoint 落本地文件，**进程重启 / 容器重建后会话记忆不丢**。本项目用 `AsyncSqliteSaver`（因为图走 async 路径，同步 SqliteSaver 不支持 `aget_tuple`）。生产规模再大可换 `PostgresSaver`，接口一致。

### 3. 为什么 SSE 双层流（progress + token）？

**答**：用户要两种实时反馈——「现在研究到哪了」（进度）+「报告逐字流出」（体验）。LangGraph 的 `astream(stream_mode=["updates", "messages"])` **单次流同时产出两类事件**：updates 模式给节点级进度，messages 模式给 LLM 逐 token 输出。前端据此渲染进度条 + 打字机效果。关键坑：writer 必须在父图顶层（不在嵌套子图），否则 token 流不传播（[langgraph#6105](https://github.com/langchain-ai/langgraph/issues/6105)）。

### 4. 多模型路由怎么省钱？

**答**：3 个并行 researcher 是调用大户（每个都联网 + 调 LLM），用免费的 `glm-4-flash`；只有质量关键的 summarize / writer / reviewer 用 `glm-4`。对比全用 glm-4，约省 80% 成本。

### 5. 审稿回路怎么防死循环？

**答**：reviewer 节点带 `rewrite_count` 计数器，每次重写 +1，达到 `MAX_REWRITES=3` 强制 PASS。条件边 `review_route` 检查 `decision == "pass" or rewrite_count >= max_rewrites` → END，否则 → writer。

### 6. 为什么 async 全链路？

**答**：researcher 节点要真实联网（web_search 是 async，配合 Semaphore 限流）。LangGraph 规则：**图里有 async 节点 → 整条调用链必须 async**（ainvoke / astream）。这恰好为 SSE 流式（本身就是 async）铺平了路。

---

## 🚀 快速开始

### 本地运行

```bash
# 1. 配置 API Key（从仓库根的 .env，或在此目录建 .env）
cp .env.example .env
# 编辑 .env，填入 ZHIPUAI_API_KEY（获取：https://bigmodel.cn/）

# 2. 安装依赖
make install          # 或 pip install -r requirements.txt

# 3a. 启动 Web 服务（推荐）
make run              # 或 python -m uvicorn api.main:app --reload
# 浏览器打开 http://localhost:8000

# 3b. 或用 CLI
make cli              # 默认主题
make cli T="你的研究主题"
```

### Docker 部署

```bash
# 配好 .env 后
cp .env.example .env  # 填 ZHIPUAI_API_KEY
make docker-up        # docker compose up -d
# 浏览器打开 http://localhost:8000，记忆持久化在 ./data/ 卷
make docker-down      # 停止
```

> 重启容器后会话记忆不丢（sqlite 挂载在 volume），这是相对教学版的核心生产能力。

---

## 📡 API 文档

启动服务后访问 `http://localhost:8000/docs` 看交互式文档（FastAPI 自动生成）。

### `POST /api/research`（SSE 流式）

**请求**：
```json
{ "topic": "2024 年 AI Agent 技术进展", "thread_id": "可选，用于记忆/隔离" }
```

**响应**：`text/event-stream`，事件类型：

| event | data | 说明 |
|-------|------|------|
| `progress` | `{node, label, status, ...}` | 节点级进度（研究完成/报告生成/审稿通过）|
| `token` | `{node, content}` | writer 逐 token 输出（打字机效果）|
| `done` | `{report, findings, review_decision, rewrite_count}` | 最终结果 |
| `error` | `{message}` | 异常 |

**前端示例**见 [`static/index.html`](static/index.html)（fetch + ReadableStream 解析 SSE）。

### `GET /api/health`

```json
{ "status": "ok", "persistent": true, "smart_model": "glm-4", "fast_model": "glm-4-flash" }
```

---

## 📁 项目结构

```
research-assistant/
├── README.md                     ← 你在这里
├── cli.py                        ← CLI 入口（调试用）
├── Dockerfile / docker-compose.yml / Makefile
├── requirements.txt / .env.example / pytest.ini
├── src/research_assistant/
│   ├── config.py                 ← pydantic-settings 配置中心
│   ├── state.py                  ← ResearchState / SystemState（TypedDict + reducer）
│   ├── models.py                 ← 多模型工厂（smart/fast）
│   ├── tools.py                  ← web_search（真实搜索 + 限流 + 兜底）
│   ├── nodes.py                  ← split/researcher/summarize/writer/reviewer
│   ├── graph.py                  ← 双层图组装（依赖注入）
│   ├── persist.py                ← SqliteSaver / AsyncSqliteSaver 工厂
│   ├── service.py                ← 服务层（invoke + stream_research）
│   └── logging_config.py         ← 结构化日志（timed_node 装饰器）
├── api/
│   ├── main.py                   ← FastAPI app（lifespan + 路由）
│   └── schemas.py                ← Pydantic 请求/响应模型
├── static/index.html             ← 极简聊天前端
└── tests/                        ← 25 个单元测试（不联网/不调真实 LLM）
```

---

## 🔗 课程能力复用映射（证明深度）

本项目不是空中楼阁——每一项技术都来自前 36 课的扎实学习：

| 本项目能力 | 来源课程 | 具体技术 |
|-----------|---------|---------|
| 并行 map-reduce | workflow L04 | `Send` fan-out + `operator.add` reducer |
| 子图作为节点 | workflow L03 | `research_subgraph` 嵌入父图 |
| 共享 State 通信 | workflow L05 | `findings` 字段跨层回流 |
| 多模型路由 | workflow L06 | glm-4 / glm-4-flash 分工 |
| 审稿条件边 | workflow L01 | supervisor 动态路由思想 |
| Checkpointer | framework L08 | 跨轮记忆（升级到持久化）|
| Mermaid 可视化 | framework L09 | `graph.get_graph().draw_mermaid()` |
| LangGraph StateGraph | framework L06 | 节点 + 边 + 条件路由 |
| 联网搜索 | agent L09 | DuckDuckGo（升级到 async + 限流）|
| 工具错误兜底 | agent L04 | try/except 返回友好提示 |
| LCEL / ChatZhipuAI | framework L01-L02 | LLM 调用抽象 |

---

## 💼 简历话术

### 一句话版

> 基于 LangGraph 的多智能体并行研究系统，支持真实联网检索、审稿迭代、SSE 流式输出、SqliteSaver 持久化，Docker 一键部署。

### 三句话版（简历项目栏）

> **AI 研究分析助手**（Python · LangGraph · FastAPI · Docker）
> - 设计双层 LangGraph 图（并行研究子图 + 审稿父图），3 个 researcher 用 `Send` 并行检索，配合 Semaphore 限流，相比串行约 2-3× 加速
> - 多模型路由降本（glm-4-flash 并行执行 + glm-4 决策写作，省约 80% 成本）+ reviewer 审稿回路（条件边 + 防死循环）提升报告质量
> - FastAPI + SSE 双层流式（进度 + token 逐字输出），SqliteSaver 跨重启持久化，25 单元测试，Docker 一键部署

### 面试深聊版（按考点展开）

- **架构选型**：「为什么用双层图？」→ 关注点分离 + 子图可独立测试 + 父图流程清晰
- **性能优化**：「多模型怎么省钱？」→ 执行类节点用免费 flash，质量类用 glm-4，成本省 80%
- **流式设计**：「SSE 双层怎么实现？」→ `astream(stream_mode=["updates","messages"])` 单流双模式，规避嵌套子图 token 不传播的坑
- **工程化**：「怎么上生产？」→ 异步全链路（async 图必须配 AsyncSqliteSaver）+ Docker volume 持久化 + 健康检查 + 结构化日志
- **质量保障**：「怎么测的？」→ mock LLM 测节点逻辑、真实图测拓扑、不联网不花钱 25 测试全绿

---

## ⚠️ 已知限制 & 后续演进

| 限制 | 影响 | 演进方向 |
|------|------|---------|
| 追问会当新主题研究（父图 START 固定连 research_team）| 纯聊天场景体验一般 | 加路由节点判断「研究 vs 闲聊」 |
| SqliteSaver 单机 | 多实例无法共享会话 | 换 PostgresSaver（接口一致）|
| DuckDuckGo 国内不稳 | 部分子题检索可能降级到模型知识 | 接 SerpAPI / Bing / 自建搜索 |
| 无 RAG 私有文档检索 | 研究依赖公网搜索 | researcher 加企业知识库检索层 |
| 无全链路 trace | 线上问题定位偏日志 | 接 LangSmith |

---

## 🧪 开发

```bash
make test          # 跑测试（25 个，约 10s）
make lint          # 语法检查所有源码
make clean         # 清理临时文件
```

测试原则：不调真实 LLM（用 mock）、不联网（测错误兜底路径）、不污染生产 db（用 InMemorySaver）。

---

## 📜 技术栈

- **框架**：LangGraph 1.2.7（图编排）+ FastAPI 0.139（服务化）+ sse-starlette（SSE）
- **LLM**：智谱 GLM-4 / glm-4-flash（多模型路由）
- **检索**：ddgs（DuckDuckGo，国内可用的更名包）
- **持久化**：langgraph-checkpoint-sqlite 3.1 + AsyncSqliteSaver（aiosqlite）
- **配置**：pydantic-settings（从 .env 读）
- **测试**：pytest + pytest-asyncio

---

*本项目是 [36 课 LLM 应用实战课程](../../README.md) 的生产级收官作品——从「会写 Agent」到「能交付生产级 AI 应用」。*
