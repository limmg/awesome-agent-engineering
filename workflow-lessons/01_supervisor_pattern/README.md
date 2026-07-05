# Lesson 01 — Supervisor 主从模式：动态路由调度

> **本课定位**：这是多智能体编排课程的**第一课**。前三门课你学的是「单 Agent + 单流程」，从本课开始进入「**多 Agent 协作**」。Supervisor 模式是多智能体最经典、最常用的拓扑——一个调度中心统一指挥若干专家。
>
> **映射的手写课**：`agent-lessons/08_multi_agent`（你手写的 3-Agent 流水线：`planner() → executor() → reviewer()`，一个写死的 `for` 循环）。

---

## 一、先回顾：你 Agent L08 手写的多智能体长什么样？

打开 `agent-lessons/08_multi_agent/code.py`，核心是 `run_multi_agent`：

```python
def run_multi_agent(client, task):
    steps = planner(client, task)              # ← 第 1 步：规划
    for round_num in range(1, MAX+2):          # ← 写死的顺序循环
        result = executor(client, task, steps) # ← 第 2 步：执行
        passed, verdict = reviewer(...)        # ← 第 3 步：审查
        if passed: return result
        task = f"{task}\n(审查意见：{verdict})" # ← 字符串拼接传信息
```

这是**写死的线性流水线**：Planner → Executor → Reviewer，顺序永远不变。

它能跑，但有三个根本性局限：

1. **流程写死，不能动态调整**：哪怕任务特别简单（比如"算 12×8"），也得走完规划→执行→审查三步。supervisor 模式能根据任务**按需跳过**。
2. **没有"调度者"角色**：顺序是代码里写死的，不是运行时决定的。真实场景里"先派给谁、要不要重做、要不要跳过"应该由一个**调度 LLM** 动态判断。
3. **Agent 间靠字符串拼接通信**：`task = f"{task}\n(审查意见：{verdict})"` 这种方式松散、易丢信息（L05 专门讲通信机制）。

**Supervisor 模式解决前两个问题。**

---

## 二、核心思想：Supervisor 模式（中心化调度）

### 什么是 Supervisor 模式？

一个**调度中心 Agent（supervisor）**居中，若干**专家 Agent（worker）**在外围。用户的请求先到 supervisor，supervisor（它本身也是个 LLM）**运行时根据任务内容**决定派给哪个 worker；worker 干完活把结果**回传**给 supervisor；supervisor 看了结果，再决定下一步派给谁（或结束）。

```
                 ┌─────────────┐
          ┌──────│  supervisor  │──────┐
          │      │  (调度中心)   │      │
          │      └──────┬───────┘      │
     虚线(条件)         │ 实线(固定)       虚线(条件)
          │      ┌──────┴───────┐      │
          ▼      ▼              ▼      ▼
     ┌────────┐ ┌────────┐ ┌────────┐
     │worker A│ │worker B│ │worker C│
     │(研究员) │ │(分析师) │ │(撰写者) │
     └────────┘ └────────┘ └────────┘
```

**关键特征（对比手写 L08）**：

| | 手写 L08 流水线 | Supervisor 模式 |
|---|---|---|
| 谁决定流程顺序 | **代码写死**（`planner→executor→reviewer`） | **supervisor 运行时决定** |
| 简单任务 | 照样走全套三步 | **按需跳过**（只派必要的 worker） |
| 有没有调度者 | 没有（顺序写死） | 有（supervisor 是个 LLM） |
| 能否动态调整 | 不能 | 能（根据上一步结果改派） |
| 拓扑形状 | 一条直线（流水线） | **星型**（hub-and-spoke） |

### Supervisor 和手写 L08 的 Planner 有什么区别？

容易混淆，重点说清：

- **手写 L08 的 Planner**：只在开始时一次性输出步骤清单，之后流程就**固定**了。Planner 不参与运行时调度。
- **Supervisor**：**每一步**都参与决策。worker 回来汇报后，supervisor 重新判断"接下来该派谁"——这是真正的**动态**路由。

---

## 三、关键 API：`create_supervisor` + `create_agent`

本课用 `langgraph-supervisor` 包（需要 `pip install langgraph-supervisor`）。

### 1. 创建 worker（框架课 L07 的 `create_agent`）

每个 worker 就是一个普通 Agent，用你熟悉的 `create_agent`（框架课 L07 学过）：

```python
from langchain.agents import create_agent

researcher = create_agent(
    llm,
    tools=[get_weather, calculator],   # worker 可以自带工具
    name="researcher",                 # ⚠️ name 必须传！
    system_prompt="你是研究员，负责用工具收集事实...",
)
```

> ⚠️ **踩坑点 1（教学金矿）**：在 supervisor 系统里，`create_agent` **必须传 `name=` 参数**，否则 `create_supervisor` 会报错：
> ```
> ValueError: Please specify a name when you create your agent...
> ```
> 因为 supervisor 要靠 name 来区分"派给谁"。框架课 L07 单独用 `create_agent` 时 name 可省，但在多智能体场景必须有。

### 2. 创建 supervisor（本课主角）

```python
from langgraph_supervisor import create_supervisor

supervisor = create_supervisor(
    agents=[researcher, analyst, writer],  # 手下的小弟们
    model=llm,                             # supervisor 自己用哪个 LLM
    prompt="你是调度中心。根据任务派给 researcher/analyst/writer...",
    output_mode="full_history",            # 保留完整消息历史
)
graph = supervisor.compile()
```

`create_supervisor` 背后做了什么？
- 自动给 supervisor 生成 N 个 **handoff 工具**（`transfer_to_researcher`、`transfer_to_analyst`...），supervisor 调用哪个工具就是"派给哪个 worker"。
- 自动把每个 worker 编译成子图，连上"worker→supervisor"的回传边。
- 产出一个 `StateGraph` builder，你 `compile()` 后得到一个普通图。

### 3. 调用（和普通 LangGraph 图一样）

```python
result = graph.invoke({"messages": [{"role": "user", "content": "查北京上海天气并比较"}]})
print(result["messages"][-1].content)   # 最终回答
```

> ⚠️ **踩坑点 2**：`output_mode` 参数的合法值是 `"full_history"` 和 `"last_message"`（默认）。别写成 `"history"`（会报错）。`full_history` 保留所有中间消息（便于看清路由过程），`last_message` 只返回最后一条。

---

## 四、框架替你做了什么？

把本课 `code.py` 的 supervisor 版本和手写 L08 对照，框架省掉的活：

| 你在 L08 手写的 | supervisor 框架版 |
|---|---|
| `run_multi_agent` 里的 `for round_num` 写死顺序循环 | supervisor 运行时动态决定，不用写循环 |
| 手动判断"现在该规划/执行/审查" | supervisor LLM 自动判断派给谁 |
| `task = f"{task}\n(审查意见：{verdict})"` 字符串拼接传信息 | handoff 工具 + messages 自动传递上下文 |
| 写死 `MAX_REWORK_ROUNDS` 重做次数 | supervisor 自己决定要不要重派 |
| 简单任务也得走全套 | supervisor **按需跳过**（实验 2 演示） |
| 没有可视化，读代码才知道流程 | `draw_mermaid()` 一眼看清星型拓扑 |

**框架的代价**：每派一次任务都过一遍 supervisor（多一次 LLM 调用），比写死流水线**更贵更慢**。这是"灵活性 vs 成本"的经典取舍——L06 会专门讲多模型路由来降本。

---

## 五、手写版 vs 框架版：代码量对比

| 模块 | 手写 L08 | supervisor 版 |
|---|---|---|
| Agent 定义 | 3 个函数 + 3 个 prompt + 各自的 LLM 调用代码（~80 行） | 3 个 `create_agent(...)`（~15 行） |
| 工具定义 | 函数 + JSON Schema + Registry 三份（~30 行） | 2 个 `@tool`（~10 行） |
| 编排逻辑 | `run_multi_agent` 的 for 循环 + 重做逻辑（~30 行） | 1 个 `create_supervisor(...)` + `compile()`（~5 行） |
| 动态路由 | **做不到** | 内置 |
| **总计** | ~140 行，且只能流水线 | ~30 行，且支持动态路由 |

省的不只是代码量，更是**能力**——手写版做不到的"按需调度"，框架版开箱即用。

---

## 六、本课代码

`code.py` 做三件事：

1. **实验 1（复合任务动态调度）**：给"查北京上海天气+比较+穿衣建议"任务，观察 supervisor 依次派给 researcher（查天气）→ analyst（分析）→ writer（整理），打印完整消息流看清路由过程。
2. **实验 2（简单任务跳过 worker）**：给"算 12×8"任务，supervisor 只派 researcher，跳过 analyst/writer——体现手写 L08 做不到的"按需调度"。
3. **实验 3（星型拓扑可视化）**：打印 Mermaid 图，看清 supervisor 居中、worker 围绕的星型结构，虚线（条件边）/实线（固定边）的区别。

```bash
python workflow-lessons/01_supervisor_pattern/code.py
```

---

## 七、小结 & 下节预告

**✅ 本课要点**：
- Supervisor = **中心化调度**：一个调度 LLM 居中，运行时动态决定派给哪个 worker
- worker 用 `create_agent(name=...)` 创建（**name 必传**）
- `create_supervisor` 自动生成 handoff 工具 + 回传边，一行编排
- 星型拓扑：worker 只跟 supervisor 通信，不互相通信
- 对比手写 L08：写死的 for 循环 → 运行时动态路由，还能按需跳过

**🔜 下节预告（L02 — Swarm 与 Handoff）**：
Supervisor 模式有个特点——每个 worker 干完活都要**回中心汇报**，由中心再决定下一步。但有些场景（比如客服：先退款组、再售后组），Agent 之间可以**直接交接**，不必每次都回中心。这就是 **Swarm（去中心化）+ Handoff（状态交接）** 模式，下节课我们把 L08 的"字符串拼接传信息"升级成结构化的 handoff。

> ⚠️ **清醒认知**：supervisor 不是银弹。它的"每次回中心"机制在 Agent 多、任务长时会显著增加延迟和成本（每个 worker 完成都要过一遍 supervisor LLM）。L02 的 swarm 和 L06 的多模型路由都是为了解决这个代价。
