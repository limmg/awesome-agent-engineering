# Lesson 05 — 共享状态通信：从字符串到结构化

> **本课定位**：前 4 课里 Agent 之间已经在交换信息——L02 用 handoff、L04 用 Send。但还没系统讲过"多 Agent 到底怎么通信"。本课把**三种通信机制**讲透：消息传递（手写 L08 的方式）、共享 State、黑板模式。这是 Agent L08 README 明确提到但没实现的（README 提了消息/共享状态/黑板三种，只实现了消息传递）。
>
> **映射的手写课**：`agent-lessons/08_multi_agent`（你手写 L08 用 `task = f"{task}\n(审查意见：{verdict})"` 字符串拼接传信息——这就是"消息传递"，本课用它做对照基准）。

---

## 一、先回顾：你 Agent L08 是怎么通信的？

打开 `agent-lessons/08_multi_agent/code.py`，看信息怎么在 Agent 间流动：

```python
# 规划者的输出，传给执行者
def executor(client, task, steps):
    # steps 是规划者输出的列表，拼进执行者的 prompt
    messages = [{"role": "user", "content": f"原始任务：{task}\n步骤计划：{json.dumps(steps)}..."}]

# 审查不通过，把意见拼回 task
task = f"{task}\n（上一轮审查意见：{verdict}，请改进）"  # ← 字符串拼接
```

这就是**消息传递**——Agent 的输出被**拼成字符串**塞进下一个 Agent 的 prompt。

它能跑，但 README 里明确承认了局限（三种通信方式只实现了这一种）：

| 问题 | 具体表现 |
|---|---|
| 信息易丢 | 字符串拼太长会被截断、格式混乱 |
| 无法追溯 | 中间结果藏在 prompt 字符串里，调试时看不清"谁说了什么" |
| 耦合度高 | 每个 Agent 必须知道"上游输出长什么样"才能拼 prompt |

**本课讲三种通信机制，解决这些局限。**

---

## 二、三种通信机制总览

| | ① 消息传递 | ② 共享 State | ③ 黑板模式 |
|---|---|---|---|
| **怎么传信息** | Agent 输出拼进下一个 prompt | 多 Agent 读写 State 的**固定字段** | 所有 Agent 读写**同一个知识池** |
| **结构化** | 无（纯文本） | 有（TypedDict 字段） | 有（列表 + 标签） |
| **可追溯** | 差（拼着拼着乱了） | 好（字段分明） | 好（黑板留全貌） |
| **Agent 耦合度** | 高（要知道格式） | 中（要知道字段名） | **低**（只管读写池） |
| **适合场景** | 简单/快速原型 | 固定流程 | 松耦合/可扩展 |
| **手写 L08 用的** | ✅ 就是这个 | | |

---

## 三、机制详解

### ① 消息传递（Message Passing）

Agent 的输出直接拼进下一个 Agent 的 prompt。最简单，手写 L08 就是这种。

```python
# 规划者输出 plan（字符串）
plan = llm.invoke("...给出计划").content

# 执行者把 plan 拼进自己的 prompt
execution = llm.invoke(f"基于以下计划执行：\n{plan}").content
```

**优点**：最简单，不需要任何框架。
**缺点**：信息藏在字符串里，无结构，易截断，难追溯。

> 💡 这不是"错"的方式——对于简单任务它够用。但 Agent 多了、流程长了，就会乱。

### ② 共享 State（Shared State）

多 Agent 读写 State 的**固定字段**。每个 Agent 明确知道"我读哪个字段、写哪个字段"。

```python
class SharedState(TypedDict):
    topic: str       # 输入
    plan: str        # 规划者写
    execution: str   # 执行者写（读 plan）
    summary: str     # 总结者写（读 execution）

def planner(state: SharedState):
    plan = llm.invoke(f"主题：{state['topic']}").content  # 读 topic
    return {"plan": plan}                                  # 写 plan

def executor(state: SharedState):
    exec = llm.invoke(f"基于：{state['plan']}").content    # 读 plan
    return {"execution": exec}                              # 写 execution
```

**优点**：
- 结构化（字段分明）
- 可追溯（result 字典里有全部中间结果）
- 类型安全（TypedDict 定义）

**缺点**：Agent 之间有中等耦合——必须约定"哪个字段存什么"。

> 💡 前面 L01-L04 用的 LangGraph State 本质上就是这种机制。你已经用了 4 课，本课只是把它"命名"出来。

### ③ 黑板模式（Blackboard）

所有 Agent 读写**同一个知识池**（一个列表字段 + reducer）。Agent 之间**完全解耦**——不需要知道谁在前面、谁在后面，只管往黑板写、从黑板读。

```python
class BlackboardState(TypedDict):
    knowledge: Annotated[list[str], operator.add]  # ⭐ 黑板：所有人往这写
    answer: str

def researcher(state):
    fact = llm.invoke("给出事实").content
    return {"knowledge": [f"【事实】{fact}"]}     # 写入黑板

def analyst(state):
    all_info = "\n".join(state["knowledge"])      # 读黑板全部
    analysis = llm.invoke(f"基于：{all_info}").content
    return {"knowledge": [f"【分析】{analysis}"]}  # 也写入黑板
```

**优点**：
- **完全解耦**——researcher 不知道 analyst 存在，换掉任一 Agent 不影响其他
- 黑板保留**完整知识演进过程**（事实→分析→...）
- 容易增减 Agent（加一个"质疑者"往黑板写"疑问"即可）

**缺点**：黑板上信息多了会变嘈杂（需要标签区分，如【事实】【分析】）。

> 💡 **黑板模式的现实类比**：办公室白板。每个人往上面写，每个人都能看，不需要互相喊话。加一个人（新 Agent）只需给他一支笔（读写黑板的权限），不用改其他人的工作方式。

---

## 四、reducer：共享通信的基础

共享 State 和黑板模式都依赖 **reducer**——尤其当多个 Agent **并发写**同一字段时（L04 学过）。

```python
import operator
results: Annotated[list[str], operator.add]  # reducer = 列表拼接
```

reducer 解决的核心问题：**多个 Agent 同时往一个字段写，怎么合并不冲突？**
- 没有 reducer：后写覆盖先写（丢数据）
- `operator.add`：列表拼接（全部保留）

> ⚠️ 即使是**串行**的 Agent（一个接一个），如果它们都写同一个字段（如黑板的 knowledge），也需要 reducer——因为每次 return 都会触发"写回 State"，reducer 决定是"覆盖"还是"追加"。黑板模式必须用 reducer。

---

## 五、三种机制怎么选？

```
你的场景：
  ├── 简单任务、2-3 个 Agent、快速原型？
  │     → 消息传递（最快上手，手写 L08 风格）
  │
  ├── 固定流程（规划→执行→审查）、每步有明确输入输出？
  │     → 共享 State（字段分明，结构清晰）
  │
  └── Agent 多、经常增减、需要松耦合？
        → 黑板模式（解耦，加 Agent 不影响其他）
```

**经验法则**：
- 不确定时，从**共享 State** 开始（大多数场景的最优解）
- 只有 Agent 经常变动、或需要多个 Agent 自由贡献知识时，才上黑板
- 消息传递适合"临时拼一下"的原型，正式项目别用

---

## 六、前 4 课分别用了哪种？

| 课 | 通信机制 | 具体表现 |
|---|---|---|
| L01 supervisor | 共享 State（messages）+ handoff 消息 | worker 的输出通过 messages 回传 supervisor |
| L02 swarm | 消息传递（handoff 工具）| Agent 间用 transfer_to_xxx 交接控制权+上下文 |
| L03 子图 | 共享 State（messages 对齐）| 父图子图通过共享 messages 字段对接 |
| L04 并行 | 共享 State（results + reducer）| 并行 worker 通过 results 字段 + operator.add 合并 |
| **L05 本课** | **三种全部演示** | 系统对比，看清每种适合什么 |

你会发现：**共享 State 是最常用的**（L01/L03/L04 都用），黑板模式适合特殊场景（松耦合），消息传递是手写的原始方式。

---

## 七、本课代码

`code.py` 用同一个任务（研究 AI Agent 应用场景）做三种通信机制各一遍：

1. **实验 1（消息传递）**：复刻手写 L08 的字符串拼接，展示其局限
2. **实验 2（共享 State）**：planner/executor/summarizer 各读写固定字段
3. **实验 3（黑板模式）**：researcher/analyst/writer 全往 knowledge 池写
4. **总结**：三种机制对比表 + 选型建议

```bash
python workflow-lessons/05_shared_state/code.py
```

---

## 八、小结 & 下节预告

**✅ 本课要点**：
- 三种通信机制：消息传递（手写 L08）、共享 State（固定字段）、黑板模式（知识池）
- 消息传递最简单但易乱；共享 State 结构化最常用；黑板模式最解耦
- reducer 是共享 State/黑板的基础：解决多 Agent 写同一字段的合并
- Agent L08 README 提了三种但只实现了一种——本课补全另外两种
- 选型：不确定时用共享 State，松耦合时用黑板，原型时用消息传递

**🔜 下节预告（L06 — 多模型路由与网络拓扑）**：
前 5 课所有 Agent 都用同一个模型（glm-4）。但真实项目里不同 Agent 适合不同模型——supervisor 用贵的聪明的（glm-4），worker 用便宜的快的（glm-4-flash）。L06 讲多模型路由 + 四种网络拓扑（星型/环型/网状/层级）总览，是 LangGraph 主干段的收官。

> ⚠️ **清醒认知**：黑板模式听起来很美（完全解耦），但它的代价是"黑板会越来越嘈杂"——随着 Agent 增多，知识池里堆满各种标签的信息，读取时要做过滤/优先级判断。生产环境的黑板系统通常需要配套"黑板清理"或"信息老化"机制，否则会被过时信息淹没。
