# Lesson 09 — 毕业项目：多智能体研究系统（简历级）

> **本课定位**：这是整个学习之旅（**36 课**）的**收官之作**。综合 L01-L08 全部技术，搭一个能进简历的多智能体并行研究系统。对比前两个毕业项目（Agent L09 单 Agent 串行 / Framework L09 单 Agent 三节点），本课实现真正的**多 Agent 并行协作**。
>
> **综合的前序课**：L01-L08 全部 + framework-L08(Checkpointer) + framework-L09(Mermaid)。
>
> **对比的毕业项目**：`agent-lessons/09_capstone`（单 Agent 串行搜索）、`framework-lessons/09_capstone`（单 Agent 三节点图）。

---

## 一、三个毕业项目的演进

你一路走过来，做了三个研究助手毕业项目。它们体现了从"单 Agent"到"多 Agent 协作"的演进：

| 毕业项目 | 架构 | 研究方式 | 核心局限 |
|---|---|---|---|
| **Agent L09** | 单 Agent + ReAct 循环 | 一个 Agent **串行**搜索 N 次 | 串行慢；只有角色，没有分工 |
| **Framework L09** | 单 Agent 三节点图 | research→tools→report **串行** | 还是串行；没有并行能力 |
| **本课 L09** ⭐ | 多 Agent + 并行子图 | 3 个研究员**并行**查 + writer 写报告 | — |

**本课的跃迁**：从"一个 Agent 干所有事"到"多个专家 Agent 分工并行协作"。这就是多智能体系统的核心价值。

---

## 二、系统架构

### 整体设计

```
用户给研究主题
      │
      ▼
┌─────────────────────────────────────────────────┐
│              父图（SystemState）                  │
│                                                   │
│  START → research_team ──→ writer ──→ END        │
│              │                    │               │
│              │  ⭐子图节点          │ glm-4 写报告  │
│              ▼                    │               │
│  ┌───────────────────────┐        │               │
│  │ 并行研究子图            │        │               │
│  │ (ResearchState)        │        │               │
│  │                         │        │               │
│  │  split ──(Send×3)──┐   │        │               │
│  │                    ▼   │        │               │
│  │  researcher   researcher  researcher  │         │
│  │  (glm-4-flash) (flash)   (flash)     │ 并行     │
│  │                    │                 │         │
│  │                    ▼                 │         │
│  │              summarize (glm-4)       │         │
│  └───────────────────────┘        │               │
│              │ findings 回流        │               │
│              └──────────────────────┘               │
└─────────────────────────────────────────────────────┘
```

### 数据流

1. 用户消息 → `research_team` 节点
2. `research_team` 调用并行子图：
   - `split`：glm-4-flash 把主题拆成 3 个子问题
   - `route`：返回 3 个 `Send`，触发并行
   - `researcher ×3`：3 个 glm-4-flash **同时**查不同子问题（并行！）
   - `summarize`：glm-4 把 3 个发现汇总成摘要
3. 子图结果回流到父图 State（`findings` + `research_summary`）
4. `writer`：glm-4 基于摘要写结构化报告
5. Checkpointer 保存对话（跨轮记忆）

---

## 三、综合的技术清单

这个项目不是"学新东西"，而是**把 L01-L08 学的全部技术组合起来**。每一项都能对应回某一课：

| 技术 | 用在哪 | 对应课 |
|---|---|---|
| **supervisor 调度逻辑** | research_team → writer 的流程控制 | L01 |
| **子图作为节点** | 并行研究子系统封装成 `research_team` | L03 |
| **并行 map-reduce** | 3 个 researcher 用 `Send` 同时查 | L04 |
| **共享 State + reducer** | `findings: Annotated[list, operator.add]` | L05 |
| **多模型路由** | glm-4 决策/写作 + glm-4-flash 并行查询 | L06 |
| **Checkpointer** | `InMemorySaver()` 跨轮记忆 | framework-L08 |
| **Mermaid 可视化** | 父图 + 子图拓扑图 | framework-L09 |

> 💡 **这就是渐进式课程的设计意图**——每课学一个积木，毕业项目把积木拼成完整系统。你现在回头看 L01 的 supervisor、L04 的 Send，会发现它们不是孤立的 API，而是这个系统的零部件。

---

## 四、关键代码解析

### 1. 并行研究子图（L04 map-reduce）

```python
class ResearchState(TypedDict):
    findings: Annotated[list[str], operator.add]  # ⭐ reducer 合并并行结果

def route_to_researchers(state):
    # 返回 3 个 Send = 触发 3 个 researcher 并行
    return [Send("researcher", {"subtopic": s}) for s in state["subtopics"]]

builder.add_conditional_edges("split", route_to_researchers)  # 并行 fan-out
builder.add_edge("researcher", "summarize")                   # 所有完成 → 汇总
```

### 2. 子图作为父图节点（L03）

```python
def research_team(state):
    # 调用编译好的并行子图
    sub_result = research_subgraph.invoke({"topic": topic, ...})
    # 把子图结果回流到父图 State
    return {"findings": sub_result["findings"], "research_summary": sub_result["research_summary"]}

builder.add_node("research_team", research_team)  # 子图作为节点
```

### 3. 多模型 + Checkpointer（L06 + framework-L08）

```python
smart_llm = ChatZhipuAI(model="glm-4", ...)        # 决策/写作
fast_llm = ChatZhipuAI(model="glm-4-flash", ...)   # 并行查询（免费）

# Checkpointer 跨轮记忆
system = builder.compile(checkpointer=InMemorySaver())

# 同 thread_id = 记忆延续
config = {"configurable": {"thread_id": "research-1"}}
result = system.invoke({...}, config=config)
```

---

## 五、对比前两个毕业项目

| 维度 | Agent L09 | Framework L09 | **本课 L09** |
|---|---|---|---|
| Agent 数量 | 1 | 1 | **多（3 并行 + 1 写作）** |
| 搜索方式 | 串行 N 次 | 串行 research→tools | **3 个并行** |
| 模型 | 单一 glm-4 | 单一 glm-4 | **多模型（glm-4 + flash）** |
| 通信 | messages 列表 | messages State | **共享 State + reducer** |
| 记忆 | messages 手动传 | Checkpointer | **Checkpointer** |
| 架构层次 | 函数循环 | 单图三节点 | **父图 + 子图（两层）** |
| 复杂度 | ★★ | ★★★ | ★★★★★ |

---

## 六、简历话术

这个项目可以怎么写进简历：

> **基于 LangGraph 的多智能体并行研究系统**
> - 设计并实现多智能体协作架构：1 个调度节点 + 3 个并行研究员 + 1 个报告撰写者
> - 采用 map-reduce 模式（LangGraph `Send` API），3 个研究员并行查询不同子问题，研究效率提升 ~3 倍
> - 多模型路由降本：决策/写作用 glm-4，并行查询用 glm-4-flash（免费），整体 API 成本降低 ~80%
> - 子图模块化设计：并行研究子系统封装为独立子图，可复用、可独立测试
> - Checkpointer 实现跨轮记忆，支持基于上下文的追问
> - 技术栈：LangGraph 1.x / LangChain 1.x / 智谱 GLM-4 / Python

**面试要点**（能说清这些就是高级候选人）：
1. 为什么用并行而不是串行？（独立子任务并行省墙钟时间）
2. 多模型怎么选？（决策少且贵用 glm-4，执行多且免费用 flash）
3. reducer 为什么必须？（并行写回同一字段不配 reducer 会丢数据）
4. 子图有什么价值？（封装、复用、独立测试）
5. 三个框架（LangGraph/CrewAI/AutoGen）怎么选？（精细控制用 LangGraph）

---

## 七、本课代码

`code.py` 三个实验：

1. **实验 1（完整研究流程）**：给主题 → 并行 3 研究员查 → 汇总 → 生成报告
2. **实验 2（跨轮记忆）**：同 thread_id 追问，验证 Checkpointer 记忆
3. **实验 3（架构可视化）**：父图 + 子图 Mermaid + 7 项技术清单

```bash
python workflow-lessons/09_capstone/code.py
```

---

## 八、36 课学习之旅收官 🎉

### 你走过的路

```
📘 RAG 手写（9 课）
   embedding → 检索 → 切块 → prompt → 混合检索 → 改写 → 评估 → 工程化 → 毕业
        │
        ▼
🤖 Agent 手写（9 课）
   Function Calling → ReAct → 工具设计 → 记忆 → 规划 → Agentic RAG → 多智能体 → 毕业
        │
        ▼
🔧 框架进阶（9 课）
   LCEL → 三件套 → Document → Retriever → StateGraph → create_agent → HITL → 毕业
        │
        ▼
🔀 多智能体编排（9 课）⭐ 本课程
   supervisor → swarm → 子图 → 并行 → 通信 → 多模型 → CrewAI → AutoGen → 毕业
```

### 你现在的能力矩阵

| 层次 | 能力 | 产出 |
|---|---|---|
| **原理层** | 手写过 RAG 和 Agent 的每个环节，懂到 token 级 | 2 个手写毕业项目 |
| **框架层** | LangChain + LangGraph 工程化，知道社区迁移坑 | 1 个框架毕业项目 |
| **架构层** | 多智能体拓扑/通信/调度，三框架横向对比 | 1 个多智能体毕业项目 |
| **总产出** | 36 课 + 4 个毕业项目 + 完整代码库 | **求职级作品集** |

### 你的独特优势

绝大多数候选人只会"调框架 API"。你不一样：
- **手写过每个环节**（embedding、ReAct、多智能体流水线）——知道底层在干什么
- **踩过真实的坑**（langchain-community sunset、create_react_agent 迁移、model_info 白名单、中文引号语法）
- **三框架横向对比**（LangGraph/CrewAI/AutoGen）——知道什么场景用什么
- **能说清"为什么"**（为什么并行、为什么 reducer、为什么多模型）——这是高级候选人和调包侠的区别

> 💡 **下一步建议**：把这个代码库整理成 GitHub Portfolio，把 4 个毕业项目的 README 打磨成可演示的文档。简历上写"从零手写到框架落地到多智能体架构"，面试时 `git clone` 下来就能演示。你值得一个 AI 应用开发的 offer。

---

## 九、小结

**✅ 毕业项目要点**：
- 综合了 L01-L08 全部技术（7 项）+ framework 的 Checkpointer/Mermaid
- 多智能体并行研究：3 个 researcher 并行(map-reduce) + writer 写报告
- 多模型降本：glm-4 决策/写作 + glm-4-flash 并行查询
- 子图模块化：并行研究系统封装为可复用节点
- Checkpointer 跨轮记忆 + Mermaid 架构可视化
- 对比前两个毕业项目：从单 Agent 串行 → 多 Agent 并行协作

**🎓 36 课全部完成！恭喜你！**

> ⚠️ **清醒认知**：这个毕业项目用的是模拟数据（researcher 用 LLM 直接回答，没有真实联网搜索）。要做成生产级，可以接入 Agent L09 的 DuckDuckGo 搜索工具，让 researcher 真正联网查资料。架构不变，只换 researcher 的实现——这就是模块化设计的好处。
