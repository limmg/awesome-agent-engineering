# Lesson 08 — 状态、记忆与人机协作（HITL）

> **本课定位**：LangGraph 相比手写循环的**杀手锏**。你 Agent L05 手写了 `messages` 列表管理（keep_all/truncate/summary 三策略）、L06 用图重写了 ReAct。本课给图加上**Checkpointer（状态持久化）**和 **interrupt（人机协作）**——这两件事手写循环几乎做不到优雅。
>
> **映射的手写课**：`agent-lessons/05_memory`（手写 `messages.append()`、手动维护历史、三策略对比）。

---

## 一、痛点回顾：你 Agent L05 怎么管"记忆"？

打开 `agent-lessons/05_memory/code.py`，你的多轮对话是：

```python
messages = [{"role": "system", "content": "你是助手"}]
for user_input in conversations:
    messages.append({"role": "user", "content": user_input})   # 手动存
    reply = chat(client, messages)                              # 手动传全部历史
    messages.append({"role": "assistant", "content": reply})    # 手动存
```

**记忆 = 一个 `messages` 列表，全靠你手动维护**。你还手写了三种窗口策略（`keep_all` / `truncate_messages` / `compress_with_summary`）来控制历史长度。这能跑，但有三个痛点：

1. **状态不自动持久化**：程序退出，`messages` 就丢了。想跨进程/跨会话记住上下文，你得自己存数据库。
2. **多会话隔离靠手写**：两个用户同时聊，你得用 `user_id` 维护多个 `messages` 列表，手动路由。
3. **无法在中间暂停**：Agent 跑到一半想"问问人再继续"？你的 `for` 循环没法优雅地暂停-恢复。

**LangGraph 的 Checkpointer + interrupt 就是为了解决这些。**

---

## 二、核心概念一：Checkpointer —— 状态自动持久化

### 什么是 Checkpointer？

Checkpointer 是 LangGraph 的**状态存档机制**。给图加上它之后，**图的 State 在每次节点执行后自动存档**，下次可以从存档恢复。

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()                      # 创建一个内存检查点存储
graph = builder.compile(checkpointer=checkpointer) # 编译时挂上
```

### `thread_id` —— 会话隔离的钥匙

这是最关键的概念。`thread_id` 标识"一次对话会话"：

```python
config = {"configurable": {"thread_id": "user-001"}}
graph.invoke({"messages": [...]}, config=config)   # 同一 thread_id 自动共享状态
```

- **同一 `thread_id`**：多次 `invoke` 自动共享同一个 State（记忆延续）
- **不同 `thread_id`**：状态完全隔离（互相看不到，等于"失忆"）

### 对比 Agent L05 的手写

| | Agent L05 手写 | LangGraph + Checkpointer |
|---|---|---|
| 存历史 | `messages.append(...)` 手动 | 节点返回后**自动存档** |
| 多会话隔离 | 手写 `user_id → messages` 字典 | `thread_id` 自动隔离 |
| 跨轮记忆 | 手动传完整 messages | 同 thread_id 自动带历史 |
| 持久化到磁盘 | 自己存数据库 | 换 `SqliteSaver` 即可（进阶）|

> 你 Agent L05 手写的 `keep_all` 策略（全保留），在 LangGraph 里是 Checkpointer 的**默认行为**——同 thread_id 自动保留全部历史。你写的 `truncate`/`summary` 策略，仍可在节点函数里实现（原理不变，只是框架帮你存档了）。

### 三种 Checkpointer（了解）

| Checkpointer | 存哪 | 适用 |
|-------------|------|------|
| `MemorySaver` | 进程内存 | 开发/测试（进程退出就丢）|
| `SqliteSaver` | 本地 SQLite 文件 | 单机持久化（需装 `langgraph-checkpoint-sqlite`）|
| `PostgresSaver` | PostgreSQL 数据库 | 生产级多实例共享 |

本课用 `MemorySaver`（够演示）。换 `SqliteSaver` 只改一行，图的代码完全不变。

---

## 三、核心概念二：interrupt —— 人机协作（HITL）

这是 LangGraph 最强大的特性，手写循环几乎做不到。

### 痛点：Agent 要做"危险操作"前，怎么先问人？

想象一个花钱的 Agent：用户说"帮我买 1000 元的咖啡"，Agent 调用 `spend_money(1000)`。但万一用户说错了？1000 元的咖啡合理吗？

**你希望：Agent 在执行 `spend_money` 前，暂停，问人"确认要花 1000 元吗？"，人同意才执行。**

手写循环里，这要在 `for` 循环里塞 `input()` 等用户输入——但这破坏了 Agent 的自动性，而且无法在生产环境（无终端）优雅实现。

### `interrupt()` —— 优雅地暂停

LangGraph 的 `interrupt()` 函数让图**在某个节点里暂停**，把控制权交回调用方：

```python
from langgraph.types import interrupt

def call_tools_with_approval(state):
    tool_calls = state["messages"][-1].tool_calls
    # ⭐ 在执行工具前，interrupt 暂停，把"要执行什么"告诉外部
    approval = interrupt({
        "question": "确认要执行以下工具吗？",
        "tool_calls": [...],
    })
    # interrupt 返回的值 = 外部恢复时传进来的值
    if approval == "yes":
        return ToolNode(tools).invoke(state)   # 批准 → 执行
    else:
        return {"messages": [HumanMessage("用户拒绝了。")]}
```

### 两步式调用：暂停 → 恢复

`interrupt` 把一次完整的图执行拆成**两次 `invoke`**：

```python
config = {"configurable": {"thread_id": "t1"}}

# 第 1 次：跑到 interrupt 处暂停，返回暂停信息
result = graph.invoke({"messages": [...]}, config=config)
# result["__interrupt__"] 里有"问用户什么"

# 第 2 次：用户确认后，用 Command(resume=...) 恢复
from langgraph.types import Command
result = graph.invoke(Command(resume="yes"), config=config)
# 图从暂停处继续，tool 执行，给出最终答案
```

**关键**：这需要 Checkpointer（因为暂停后要恢复状态）。没有 Checkpointer，interrupt 无法工作——暂停了就没法续。

### HITL 的真实应用场景

| 场景 | interrupt 怎么用 |
|------|----------------|
| 花钱/发邮件/删数据 | 执行前 interrupt，等人确认 |
| 敏感信息查询 | interrupt 问"你确定要查吗" |
| Agent 不确定时 | interrupt 把不确定的选项给人选 |
| 工具执行结果审查 | interrupt 让人看结果再决定是否继续 |

> 这是手写 Agent 循环**几乎做不到**优雅实现的事。你 Agent L03 的 `for` 循环里塞 `input()` 会破坏自动化、无法上生产。图的 interrupt 是声明式的、状态安全的、可恢复的。

---

## 四、手写 vs 框架：本课的终极对比

| 能力 | Agent L05 手写 | LangGraph（本课）|
|------|---------------|-----------------|
| 跨轮记忆 | `messages.append()` 手动 | 同 thread_id 自动 |
| 多会话隔离 | 手写字典路由 | thread_id 自动隔离 |
| 持久化 | 自己存 DB | 换 Checkpointer 类 |
| 暂停问人 | `input()`（无法上生产）| `interrupt()` + `Command(resume=)` |
| 恢复执行 | 自己存状态续跑 | Checkpointer 自动恢复 |

**但记忆的原理没变**：仍然是"把历史传给模型让它看起来像有记忆"。Checkpointer 只是帮你**自动存档、自动隔离、自动恢复**——本质还是你在 Agent L05 学的那套。

---

## 五、本课代码

`code.py` 两个实验：

1. **跨轮记忆**：同 thread_id 记住名字，不同 thread_id 失忆（对比 Agent L05 的手写 messages）
2. **人机协作**：花钱工具执行前 interrupt 暂停 → Command(resume) 恢复（对比手写做不到的优雅暂停）

---

## 六、小结 & 下节预告

✅ 现在你应该明白：
- Checkpointer 让图的 State 自动存档、按 thread_id 隔离
- 同 thread_id = 记忆延续，不同 thread_id = 互相隔离
- `interrupt()` + `Command(resume=)` 实现优雅的人机协作（手写做不到）
- 记忆原理仍是 Agent L05 学的那套，框架是自动化的封装

🔜 **L09 毕业项目**：用 LangGraph 把你 Agent L09（研究助手）重做成生产级图结构——多节点 + 条件回路 + HITL + 部署演示。综合 L06-L08 全部技术，简历级作品。
