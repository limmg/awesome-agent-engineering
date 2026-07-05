# Lesson 02 — Swarm 与 Handoff：Agent 间状态交接

> **本课定位**：L01 学了 supervisor（中心化），本课学它的"反面"——**Swarm（去中心化）**。两者是 2024 年 OpenAI 和 LangChain 推动的两种主流多智能体拓扑。理解它们的取舍，是架构师的基本功。
>
> **映射的手写课**：`agent-lessons/08_multi_agent`（你手写 L08 时，Agent 之间用 `task = f"{task}\n(审查意见：{verdict})"` **字符串拼接**传递信息——本课用结构化的 **handoff** 替代）。
>
> **对比的前序课**：`workflow-lessons/01_supervisor_pattern`（L01 的中心化调度，本课直接对比）。

---

## 一、L01 的 supervisor 有什么问题？

回顾 L01：supervisor 系统里，每个 worker 干完活都要**回中心汇报**（`transfer_back_to_supervisor`），由 supervisor 再决定下一步派给谁。

```
用户 → supervisor → researcher → 回 supervisor → analyst → 回 supervisor → writer → 回 supervisor → 结束
                       ↑ 每次交接都过中心 ↑
```

这个"每次回中心"带来了**额外开销**：N 个 worker 走完整个流程，supervisor 这个中心 LLM 要被调用 N+1 次。流程越长，中心越是瓶颈（延迟 + 成本）。

**但很多场景根本不需要中心！** 比如客服：

> 用户要退款 → 分诊员一看是退款 → 转给退款专员 → 退款专员处理完 → 转给售后确认

这个流程里，分诊员、退款专员、售后专员**各自知道自己下一步该转给谁**，不需要每次都回某个"调度中心"重新判断。这就是 **Swarm** 的用武之地。

---

## 二、核心思想：Swarm（去中心化）

### 什么是 Swarm 模式？

没有中心调度节点。每个 Agent 都能**直接 handoff 给其他 Agent**（前提是配置了对应的 handoff 工具）。控制权在 Agent 之间"传递"，像接力棒。

```
    Swarm（网状）                  Supervisor（星型，L01）

  ┌────────┐                      ┌─────────────┐
  │ triage │──────┐          ┌────│  supervisor  │────┐
  └────┬───┘      │          │    └──────┬──────┘    │
       │          ▼          │           │           ▼
       │     ┌────────┐      ▼      ┌────────┐  ┌────────┐
       └────▶│ refund │     triage  │refund  │  │analyst │
             └────┬───┘      └──┬───┘└────────┘  └────────┘
                  │             │                    ▲
                  ▼             └────────────────────┘
             ┌────────────┐      （全都汇聚到中心）
             │after_sales │
             └────────────┘

  Agent 间直接交接             全都经过 supervisor 中转
  无中心，网状                 有中心，星型
```

### 两种拓扑的本质区别

| | Supervisor（L01，星型）| Swarm（本课，网状）|
|---|---|---|
| 有没有中心 | 有（supervisor 调度）| **没有** |
| Agent 通信 | worker 只跟 supervisor | **Agent 之间直接 handoff** |
| 谁决定流程 | supervisor LLM 运行时决定 | **每个 agent 自己决定**（靠 prompt + handoff 工具）|
| 用户消息先到谁 | supervisor（中心接活）| **必须指定 `default_active_agent`** |
| LLM 调用次数 | 多（每次交接过中心）| **少**（直接交接，不过中心）|
| 拓扑形状 | 星型（hub-and-spoke）| 网状（mesh）|
| 适合场景 | 流程不可预测、需中心决策 | 流程相对固定、Agent 各知下一步 |

### Handoff 是什么？

Handoff（交接）= **一个 Agent 把"控制权 + 完整对话上下文"转交给另一个 Agent**。

在 langgraph-swarm 里，handoff 的实现是：给每个 Agent 配一个 **handoff 工具**（`transfer_to_xxx`）。这个工具本身不"做"什么业务，它只是一个**信号**——表示"我现在把活儿交给 xxx 了"。

```python
from langgraph_swarm import create_handoff_tool

# 给 triage 配两个交接工具：能转给 refund 或 after_sales
triage = create_agent(
    llm,
    tools=[
        create_handoff_tool(agent_name="refund"),       # 转给退款专员
        create_handoff_tool(agent_name="after_sales"),  # 转给售后专员
    ],
    name="triage",
    system_prompt="你是分诊员，只分类转交...",
)
```

> 💡 **handoff 本质是个工具调用**：LLM 决定调用 `transfer_to_refund` 工具时，框架就把控制权（和整个对话历史）转给 refund agent。所以 handoff **是否发生完全取决于 LLM 是否调这个工具**——这就是为什么 prompt 设计很关键（要明确告诉 Agent 何时该转交）。

---

## 三、关键 API：`create_swarm` + `create_handoff_tool`

本课用 `langgraph-swarm` 包（需要 `pip install langgraph-swarm`）。

### 1. 给 Agent 配 handoff 工具

```python
from langgraph_swarm import create_handoff_tool

refund = create_agent(
    llm,
    tools=[create_handoff_tool(agent_name="after_sales")],  # 退款完能转售后
    name="refund",
    system_prompt="你是退款专员，处理完退款必须转给 after_sales。",
)
```

对比 L01 的 supervisor：那里 worker **不需要** handoff 工具（因为它们只跟 supervisor 通信）。swarm 里每个 agent **必须** 配 handoff 工具，否则它没法把控制权交出去（只能自己处理到底）。

### 2. 创建 Swarm

```python
from langgraph_swarm import create_swarm

graph = create_swarm(
    agents=[triage, refund, after_sales],
    default_active_agent="triage",   # ⚠️ 必传！第一个接用户消息的 agent
).compile()
```

对比 L01 的 `create_supervisor`：

| | `create_supervisor`（L01）| `create_swarm`（本课）|
|---|---|---|
| 有 `model=` 参数 | 有（supervisor 自己是个 LLM）| **没有**（没有中心 LLM）|
| 有 `prompt=` 参数 | 有（指挥 supervisor 怎么调度）| **没有** |
| 有 `default_active_agent` | 没有（supervisor 默认接活）| **必传**（谁第一个接用户？）|
| `agents` 里的 worker 需要 handoff 工具 | 不需要 | **需要** |

> ⚠️ **为什么 `default_active_agent` 必传？** 因为 swarm 没有中心节点，框架必须知道"用户消息先送到哪个 agent"。这跟 supervisor 不同——supervisor 系统里消息总是先到 supervisor。

### 3. 调用（和普通图一样）

```python
result = graph.invoke({"messages": [{"role": "user", "content": "我要退款订单123"}]})
print(result["messages"][-1].content)
```

---

## 四、框架替你做了什么？

把本课的 swarm 版和手写 L08 对照：

| 你在 L08 手写的 | Swarm 框架版 |
|---|---|
| `task = f"{task}\n(审查意见：{verdict})"` 字符串拼接传信息 | handoff 工具**自动传递完整对话上下文**，不丢信息 |
| 手写函数调用顺序（`planner()` → `executor()`）| agent 间通过 `transfer_to_xxx` 工具**动态交接** |
| 没有"控制权转移"概念（全部是函数调用）| handoff 明确表示"我把活儿交给你了" |
| 重做逻辑要自己写 for 循环 | agent 可以 handoff 回上游（after_sales→triage 重新分诊）|

**框架的代价**：swarm 没有"全局视角"——每个 agent 只看到自己收到的对话，不知道整体流程。如果流程设计不好（比如两个 agent 互相 handoff 不停），会**死循环**。supervisor 有中心把关，不容易死循环。

---

## 五、Swarm vs Supervisor：什么时候用哪个？

这是面试高频题。决策依据：

**用 Swarm 当……**
- 流程**相对固定**，每个 Agent 清楚自己下一步转给谁（客服、订单流转）
- 想要**低延迟、低成本**（省掉"回中心"的 LLM 调用）
- Agent 之间是**平级协作**（不是指挥-执行关系）

**用 Supervisor 当……**
- 流程**不可预测**，需要中心根据结果动态决策（研究、复杂分析）
- 有明确的**指挥-执行**层级（supervisor 是"大脑"，worker 是"手脚"）
- 需要**全局控制**（防止死循环、限制步数、介入审批）

> 💡 **经验法则**：不确定时先用 supervisor（更可控），发现 supervisor 成了瓶颈再考虑 swarm。这是从"中心化"到"去中心化"的演进——和微服务架构里的 monolith→microservices 逻辑一样。

---

## 六、本课代码

`code.py` 做三件事：

1. **实验 1（Swarm 去中心交接）**：客服场景 triage→refund→after_sales，观察 Agent 间直接 handoff（消息流里**没有** `transfer_back_to_supervisor`）。
2. **实验 2（对比 supervisor）**：同一个任务分别跑 swarm 和 supervisor，对比 LLM 调用次数（swarm 省"回中心"开销）。
3. **实验 3（拓扑对比）**：打印两者的 Mermaid 图，直观对比网状（swarm）vs 星型（supervisor）。

```bash
python workflow-lessons/02_swarm_handoff/code.py
```

---

## 七、小结 & 下节预告

**✅ 本课要点**：
- Swarm = **去中心化**：Agent 之间直接 handoff，不经过调度中心
- handoff 本质是工具调用（`transfer_to_xxx`），LLM 调用它 = 转交控制权
- `create_swarm` **必传 `default_active_agent`**（因为没有 supervisor 接活）
- swarm 的 worker **必须配 handoff 工具**（否则没法交接）
- 对比 L01 supervisor：swarm 省"回中心"的 LLM 调用，更快更省
- 对比手写 L08：字符串拼接 → 结构化 handoff（传递完整上下文，不丢信息）
- 代价：每个 agent 必须自己"知道何时转给谁"，prompt 设计要求更高，容易死循环

**🔜 下节预告（L03 — 子图 Subgraph）**：
L01/L02 的系统都在一张图里。但真实项目里 Agent 会越加越多，单图变成蜘蛛网。L03 学**子图**——把一个编译好的 swarm/supervisor 系统打包成一个节点，嵌入更大的图里。这是兑现框架课 L07 决策表预告的"子图/并行"的第一步（子图）。

> ⚠️ **清醒认知**：swarm 不是 supervisor 的"升级版"，而是**不同场景的不同选择**。客服用 swarm 省钱，研究用 supervisor 可控。架构没有银弹，只有取舍——这正是架构师和"调包侠"的区别。
