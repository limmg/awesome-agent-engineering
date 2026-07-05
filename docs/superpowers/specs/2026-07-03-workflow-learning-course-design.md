# 工作流与多智能体编排课程设计（workflow-lessons）

## 背景

学习者画像（已更新，完成 27 课）：
- **已完成**：RAG 9 课（手写 embedding→检索→切块→prompt→混合检索→改写→评估→工程化）、Agent 9 课（手写到 ReAct/规划/多智能体固定流水线/毕业项目）、框架进阶 9 课（LangChain/LangGraph 工程化：LCEL、三件套、Document、Retriever、StateGraph、create_agent、Checkpointer、HITL、单 Agent 三节点图）
- **已会的 LangGraph**：单 Agent + 工具循环的图化（StateGraph 三要素、MessagesState、自定义 State、create_agent、@tool、bind_tools、ToolNode/tools_condition、MemorySaver/InMemorySaver、thread_id、interrupt/Command(resume)、draw_mermaid）
- **已会的多智能体（手写 L08）**：固定三段流水线 Planner→Executor→Reviewer + 字符串消息传递 + 审查回环。但 supervisor 动态路由、group chat、handoff、共享状态、并行、辩论都只在 README 提了，没写代码
- **求职目标**：AI 应用开发（后端），偏架构师方向
- **技术选型**：继续智谱 GLM-4 + embedding-3，复用已有向量库与样例文档
- **学习形式**：沿用渐进式课程，每课三件套（README 原理 + code.py 可运行 + exercise.md 练习）

本课程的**核心定位**：前三门课解决「单 Agent + 单流程」，本课进入「**多 Agent 协作编排**」——也就是框架进阶 L07 决策表预告、但 L09 没兑现的「并行/子图/复杂图结构」。每课把"你手写过 Agent L08 的固定流水线"和"框架多智能体版"并排对比，让学习者看清：框架如何把写死的 `for` 循环变成动态的拓扑/通信/调度。

## 设计原则

1. **重架构原理，框架是载体**：每课讲透一种经典拓扑/通信/调度机制（supervisor/swarm/subgraph/parallel/state/routing），LangGraph/CrewAI/AutoGen 只是观察这些原理的三个镜头
2. **映射对比优先**：开篇回顾手写 L08 的 `run_multi_agent()`（三个函数 + for 循环 + 字符串拼 task），用框架重写，展示"框架替你做了什么"
3. **LangGraph 主干（6 课）+ 横向对比（2 课）+ 毕业综合（1 课）**：LangGraph 贯穿主线讲透架构概念，CrewAI/AutoGen 各 1 课做"同一问题不同范式"对比
4. **每课先验证 API 再写代码**：延续上一门课血泪教训，每个新 API（尤其 langgraph-supervisor/swarm、CrewAI 接国产模型、AutoGen model_info 白名单坑）进课时先端到端验证

## 技术选型

| 组件 | 版本 | 状态验证 | 作用 |
|------|------|---------|------|
| Python（.venv） | 3.11.15 | ✅ | 满足全部框架 |
| langchain | 1.3.11 | ✅ 前 27 课零破坏 | LangGraph 依赖 + 模型集成 |
| langgraph | 1.2.7 | ✅ | 主干框架（L01-L06） |
| crewai | 1.15.1 | ✅ 已调通 GLM | L07 对比框架（角色驱动） |
| autogen-agentchat | 0.7.5 | ✅ 已调通 GLM | L08 对比框架（对话驱动，异步） |
| autogen-ext[openai] | 0.7.5 | ✅ | AutoGen 接 OpenAI 兼容协议 |
| litellm | 1.91.0 | ✅ | CrewAI/AutoGen 接智谱 GLM 的桥 |
| langgraph-supervisor | 待 L01 验证 | — | supervisor prebuilt（L01） |
| langgraph-swarm | 待 L02 验证 | — | swarm prebuilt（L02） |

> **已踩到的真实教学金矿**：
> - CrewAI 接国产模型：`LLM(model='openai/glm-4')` 走 litellm + 关 `CREWAI_TRACING_ENABLED` 避免交互提示
> - AutoGen 白名单坑：非 OpenAI 模型必须手传 `model_info={vision,function_calling,json_output,...}`，否则 `ValueError`
> - AutoGen 0.4+ 异步架构（`async def run()` + `await agent.run()`），与 CrewAI/LangGraph 同步风格不同

## 目录结构

```
RAG-test/
├── workflow-lessons/              # 本课程
│   ├── README.md                  # 门课总览（三段式表格）
│   ├── 01_supervisor_pattern/
│   ├── 02_swarm_handoff/
│   ├── 03_subgraph/
│   ├── 04_parallel_mapreduce/
│   ├── 05_shared_state/
│   ├── 06_multimodel_routing/
│   ├── 07_crewai_comparison/
│   ├── 08_autogen_comparison/
│   └── 09_capstone/
├── rag-lessons/ agent-lessons/ framework-lessons/  # （已完成前三门）
└── README.md                      # 顶层总览（加第 4 行）
```

每课三件套（严格遵循前三门课规范）：`README.md`（原理+映射对比）+ `code.py`（可运行，中文注释，═══分块，main()惯例）+ `exercise.md`（5题梯度+思考题+完成标志）。

## 课时设计（共 9 节）

### 第一部分：LangGraph 多智能体拓扑（L01-L06）— 主干

---

### Lesson 01 — Supervisor 主从模式：动态路由调度
**映射手写**：Agent L08 的"主从 Orchestrator-Worker"（README 讲了但没写代码）
**核心问题**：手写 L08 是写死的 for 循环顺序，没有运行时根据内容派发。supervisor 解决"动态路由"。

**原理 README**：
- 拓扑图：1 个 supervisor + N 个 worker（supervisor 是 LLM，根据任务决定派给哪个 worker）
- 对比手写 L08 的 Planner（一次性出清单，写死顺序）vs Supervisor（每步动态决策）
- 三种调度策略：直接路由 / 广播（全派）/ 选择性路由
- `langgraph-supervisor` 包的 `create_supervisor()` API + `handoff()` 工具

**code.py**：用 `create_supervisor` 重写 Agent L08——supervisor 调度 planner/executor/reviewer 三个 worker，展示动态路由（对比手写的固定顺序）

**exercise**：对比手写 L08 的代码量；改成 4 个 worker；思考 supervisor 何时会路由错误

---

### Lesson 02 — Swarm 与 Handoff：Agent 间状态交接
**映射手写**：Agent L08 的"消息传递"（字符串拼接）—— handoff 是结构化的状态交接
**核心问题**：手写靠字符串拼 task 传递信息，handoff 用结构化消息 + 控制权转移。

**原理 README**：
- handoff 机制：Agent A 处理一部分后，把"控制权 + 上下文"交给 Agent B
- swarm vs supervisor 区别：supervisor 是中心调度（每步回中心）；swarm 是去中心（A 直接交给 B，不回中心）
- `langgraph-swarm` 的 `create_swarm()` + `handoff()` / `HandoffMessage`
- 对比手写的 `task = f"{task}\n(审查意见:{verdict})"` 字符串拼接

**code.py**：客服场景——路由 Agent → 退款 Agent → 售后 Agent，用 handoff 交接（对比手写 L08 的字符串拼）

**exercise**：加一个新 Agent；对比 supervisor vs swarm 在同一场景的 trace 差异；思考什么场景用 swarm

---

### Lesson 03 — 子图 Subgraph：模块化与复用
**映射手写**：Agent L08 的三个独立函数（planner/executor/reviewer）
**核心问题**：随着 Agent 变多，单图会变成蜘蛛网。子图 = 把一个编译好的图作为节点嵌入父图。

**原理 README**：
- 为什么需要子图：复杂度管理、团队协作、复用
- 子图 = 把 `compiled_graph` 当 `add_node` 的参数
- State 对齐：子图的 State 可以是父图 State 的子集（共享字段）或独立（通过转换对接）
- 呼应 Framework L07 决策表预告的"并行/子图"（本课兑现那个伏笔）

**code.py**：把 L02 的 swarm 客服系统封装成一个子图，嵌入更大的父图（父图加一个"前置分类 + 后置汇总"层）

**exercise**：把前 27 课的 framework-L09 研究助手图当子图嵌入；思考子图 vs 普通函数节点区别

---

### Lesson 04 — 并行执行与 Map-Reduce：fan-out 爆发
**映射手写**：Agent L08 README 提了"无法并行"但没实现
**核心问题**：多个独立子任务应该并发跑，串行浪费时间浪费钱。

**原理 README**：
- `Send` API：`add_conditional_edges` 返回 `[Send("node", data1), Send("node", data2)]` 触发 fan-out
- map-reduce 模式：map（拆分）→ 并行 worker → reduce（合并）
- reducer 必要性：并行结果要写回同一个 State 字段，必须配 reducer（`operator.add` 等）
- 对比手写 L08 的串行 executor

**code.py**：研究多个子主题——把一个大主题拆成 3 个子问题，3 个 worker 并行搜索，最后 reduce 汇总成报告

**exercise**：改并行度；对比串行 vs 并行的耗时/token；思考并行何时反而更慢（reduce 瓶颈）

---

### Lesson 05 — 共享状态通信：从字符串到结构化
**映射手写**：Agent L08 的三种通信方式（README 提了消息/共享状态/黑板，只实现了消息）
**核心问题**：多 Agent 怎么交换信息？手写只能字符串拼接，框架提供结构化共享 State。

**原理 README**：
- 三种通信机制深度对比：
  - 消息传递（手写 L08）：Agent 输出拼进下一个 prompt —— 松散、易丢信息
  - 共享 State（LangGraph）：多 Agent 读写同一 TypedDict 字段 —— 结构化、可追溯
  - 黑板模式（blackboard）：共享一个"知识池"，Agent 各取所需 —— 解耦
- LangGraph 的 reducer 机制如何解决并发写冲突
- 何时用哪种：强依赖用共享 State；松耦合用黑板

**code.py**：同一个"规划-执行-审查"任务，用①共享 State ②黑板两种方式实现，对比手写 L08 的字符串传递

**exercise**：把黑板模式加到一个新场景；思考三种通信的信息保真度

---

### Lesson 06 — 多模型路由与网络拓扑
**映射手写**：Agent L08 全程单一模型（没有路由概念）
**核心问题**：不同 Agent 适合不同模型（贵的聪明的做决策，便宜的快的做执行）。前 27 课全程单个 glm-4。

**原理 README**：
- 模型路由：按任务难度/成本/延迟选模型（glm-4 决策 / glm-4-flash 执行）
- 四种网络拓扑总览：星型（supervisor）/ 环型（流水线）/ 网状（swarm）/ 层级（hierarchy）
- 拓扑选型决策表：什么场景用什么拓扑
- 多模型编排的成本控制

**code.py**：层级拓扑——顶层 supervisor（glm-4）调度，下层各 worker 用不同模型（贵的分析+便宜的检索+快的生成）

**exercise**：加成本统计；对比单模型 vs 多模型的总花费；画自己设计的拓扑

---

### 第二部分：横向框架对比（L07-L08）

---

### Lesson 07 — CrewAI 对比：角色驱动的声明式编排
**映射对比**：同一"规划-执行-审查"任务，CrewAI 怎么写 vs LangGraph 怎么写
**核心问题**：CrewAI 用"角色 + 任务 + 编队"的声明式心智模型，vs LangGraph 的"节点 + 边"命令式图。

**原理 README**：
- CrewAI 三件套：`Agent`（角色）+ `Task`（任务）+ `Crew`（编队，含 process=sequential/hierarchical）
- 与 LangGraph 的范式对比表：声明式（角色）vs 命令式（图）；顺序自动编排 vs 手动画边
- 教学金矿：CrewAI 接国产模型（`LLM(model='openai/...')+litellm` + 关 tracing）
- hierarchical process = CrewAI 版的 supervisor（对比 L01）
- 范式选型：快速原型用 CrewAI；精细控制用 LangGraph

**code.py**：用 CrewAI 重写 L01 的 supervisor 系统（同样 planner/executor/reviewer），展示声明式写法多简洁

**exercise**：对比 CrewAI hierarchical vs LangGraph supervisor 代码量；CrewAI 的 process=sequential 实现流水线

---

### Lesson 08 — AutoGen 对比：对话驱动的群聊编排
**映射对比**：同一多 Agent 任务，AutoGen 的 GroupChat/Swarm 怎么写
**核心问题**：AutoGen 用"对话"作为一等公民（多 Agent 在一个 GroupChat 里发言），vs LangGraph 的图调度。

**原理 README**：
- AutoGen 0.4+ 重写：异步架构、event-driven、`AssistantAgent` + `Team`
- SelectorGroupChat / RoundRobinGroupChat / Swarm（用 handoff）
- 与 LangGraph swarm（L02）的对比：对话轮次驱动 vs 图边驱动
- 教学金矿：AutoGen 白名单坑（非 OpenAI 模型必须手传 `model_info`）、异步 API（`async/await`）
- 范式选型：需要 Agent 间自由对话/辩论用 AutoGen；需要确定流程用 LangGraph

**code.py**：用 AutoGen GroupChat 实现 Agent L08 exercise 里的"辩论模式"（手写课只给了骨架没实现）——补全那个坑

**exercise**：对比 AutoGen Swarm vs LangGraph swarm 的 handoff；异步 vs 同步的开发体验

---

### 第三部分：毕业项目（L09）

---

### Lesson 09 — 毕业项目：多智能体研究系统（简历级）
**综合**：把 L01-L08 的拓扑/通信/调度综合成一个能进简历的系统

**原理 README**：
- 系统设计：一个"深度研究"系统——supervisor 调度多个专家 Agent（搜索/分析/写作/审查），用并行 + 共享状态 + 多模型
- 架构图（Mermaid）：展示完整拓扑
- 与 Agent L09（单 Agent 研究助手）和 Framework L09（单 Agent 三节点图）的对比：从单 Agent 到多 Agent 协作的跃迁
- 简历话术：怎么把这个项目写进简历

**code.py**：
- 自定义 State（共享 research_findings / outline / draft 字段）
- supervisor（glm-4）调度：搜索 Agent（glm-4-flash，并行 map-reduce）→ 分析 Agent（glm-4）→ 写作 Agent → 审查 Agent（handoff 回写作）
- 用 langgraph-supervisor + 子图（L03）+ 并行（L04）+ Checkpointer 跨轮记忆
- Mermaid 可视化

**exercise**：加一个新专家 Agent；改成 swarm 拓扑对比；写简历描述

## 实施顺序（进课时的工作模式）

每课进时的固定流程（延续上一门课）：
1. **先验证 API**（尤其新包 langgraph-supervisor/swarm）：装包 + 最小 import + 端到端调通 GLM
2. **写 code.py**：先跑通真实端到端（不是 mock），作为权威验证
3. **写 README.md**：基于真实跑通的代码讲原理 + 映射对比
4. **写 exercise.md**
5. **更新 workflow-lessons/README.md 进度 + 顶层 README.md**
6. **提交 + 推送**

按"进 L0N"指令逐课推进，不批量生成。
