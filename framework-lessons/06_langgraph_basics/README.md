# Lesson 06 — LangGraph 基础：StateGraph 重写 ReAct

> **本课定位**：这是框架课程的**转折点**——从 LangChain（RAG 工程化）进入 **LangGraph（Agent 工程化）**。你用 LangGraph 的 StateGraph 把 Agent L03 手写的 `while` 循环重写成一张「状态图」。
>
> **映射的手写课**：`agent-lessons/03_react_loop`（你手写的 `run_react_agent` —— 一个 `for` 循环 + 手动管 messages + 手动判断 "Final Answer" + 手动 `json.loads(arguments)`）。

---

## 一、先回顾：你 Agent L03 手写的 ReAct 长什么样？

打开 `agent-lessons/03_react_loop/code.py`，你的核心是 `run_react_agent`：

```python
def run_react_agent(client, user_question, max_steps=10):
    messages = [system, user]
    for step in range(1, max_steps + 1):          # ← while 循环
        response = client.chat.completions.create(messages=messages, tools=TOOLS_SPEC, ...)
        msg = response.choices[0].message
        if "Final Answer" in msg.content:          # ← 手动字符串检测终止
            return msg.content
        if msg.tool_calls:                         # ← 手动判断要不要调工具
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)   # ← 手动解析参数
                result = execute_function(name, args)      # ← 手动调度执行
                messages.append({"role": "tool", ...})     # ← 手动塞回 messages
        else:
            return msg.content
```

这是一个**命令式**的循环：你用 `if/for` 手动控制"调模型 → 看有没有 tool_calls → 执行工具 → 塞回去 → 再调模型"。

它能跑，但有几个痛点：
1. **流程藏在代码里，不可视**：读代码才能知道"先调模型、再判断、再分支"——无法一眼看出整体结构。
2. **扩展难**：想加一个"自我反思"步骤？得在循环里塞 `if`，越改越乱。
3. **状态管理手动**：`messages` 列表的增删全靠你手维护。
4. **无法持久化/恢复**：循环跑到一半崩了，状态丢了，没法续跑。

**LangGraph 用「图」来解决这些问题。**

---

## 二、核心思想：Agent 就是状态机，状态机就是图

这是本课最重要的认知转变。

### 命令式（while 循环） vs 声明式（图）

| | 手写 while 循环（Agent L03）| LangGraph 图（本课）|
|---|---|---|
| 范式 | 命令式：一步步写"做什么" | 声明式：画"有哪些节点、怎么连线" |
| 流程 | 藏在 if/for 里，读代码才知道 | **可视化**：一张图能看全 |
| 分支 | `if msg.tool_calls:` 手写 | `add_conditional_edges` 声明 |
| 终止 | 手动检测 "Final Answer" 字符串 | 走到 `END` 节点自动终止 |
| 扩展 | 改循环逻辑 | 加一个节点 + 连条边 |
| 状态 | 手动管 messages | State 对象自动管理 |
| 持久化 | 没有 | Checkpointer 可存档/续跑（L08 学）|

### 图的三要素

LangGraph 的 `StateGraph` 用三个概念描述一个 Agent：

```
① State（状态）：Agent 运行中需要记住的东西（通常是 messages 对话历史）
② Node（节点）：每一步要做的事（一个函数，接收 State、返回 State 更新）
③ Edge（边）：节点之间的连线（包括条件边——根据 State 决定下一步去哪）
```

### ReAct 循环画成图

你的 ReAct 循环，本质就是这张图：

```
          ┌─────────────────────────────┐
          │                             │
          ▼                             │
     ┌─────────┐   有tool_calls   ┌─────┴───┐
START─▶│ agent   │────────────────▶│  tools  │
     │ (调模型) │                  │ (执行工具)│
     └────┬─────┘                  └─────────┘
          │ 没tool_calls
          ▼
         END（给出最终答案）
```

- **State**：`messages`（对话历史，包括 Human/AI/Tool 消息）
- **Node `agent`**：调模型（对应你手写的 `client.chat.completions.create`）
- **Node `tools`**：执行工具（对应你手写的 `execute_function`）
- **条件边**：模型返回有 `tool_calls` → 去 `tools` 节点；没有 → 去 `END`（对应你手写的 `if msg.tool_calls:`）
- **回路 `tools → agent`**：工具执行完，把结果塞回 messages，再回到 agent 调模型（对应你手写的 `messages.append(...)` 后循环继续）

**你手写的整个 while 循环，就是这张图的一次"游走"（traversal）。**

---

## 三、StateGraph 的关键 API

用 5 个 API 就能画完上面那张图：

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

builder = StateGraph(MessagesState)        # ① 指定 State 类型

builder.add_node("agent", call_model)      # ② 加节点（名字 + 函数）
builder.add_node("tools", ToolNode(tools))

builder.add_edge(START, "agent")           # ③ 加边（固定连线）
builder.add_conditional_edges(             # ④ 加条件边（根据 State 分流）
    "agent",                               #    从哪个节点出发
    tools_condition,                       #    路由函数（看最后一条消息有无 tool_calls）
)
builder.add_edge("tools", "agent")         #    tools 执行完回到 agent（形成回路）

graph = builder.compile()                  # ⑤ 编译成可执行的图
result = graph.invoke({"messages": [...]}) # 运行
```

逐个解释：

### ① State —— `MessagesState`

State 是"图中流转的数据"。最常用的 `MessagesState` 是 LangGraph 预置的，本质就是一个 `{"messages": [...]}`：

```python
# MessagesState 等价于（简化版）：
class MessagesState(TypedDict):
    messages: Annotated[list, add_messages]   # messages 列表，自动追加而非覆盖
```

> `Annotated[list, add_messages]` 是关键：它告诉 LangGraph "节点返回的新 messages 要**追加**到列表，而不是覆盖"。这就是你手写 `messages.append(...)` 的框架版——**自动合并**。

### ② Node —— 普通函数

节点就是一个 `(state) -> state_update` 的函数：

```python
def call_model(state):
    # state 是 {"messages": [...]}
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}   # 返回的会被自动追加进 state["messages"]
```

### ③ Edge —— 固定连线

`builder.add_edge(A, B)`：A 执行完无条件去 B。

### ④ Conditional Edge —— 条件分支（对应 if/else）

```python
builder.add_conditional_edges(
    "agent",              # 从 agent 节点出发
    tools_condition,      # 路由函数
)
```

`tools_condition` 是 LangGraph 预置的路由函数，它做的事等价于：
```python
# tools_condition 的逻辑（简化）：
def tools_condition(state):
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:     # 有工具调用
        return "tools"          # → 去 tools 节点
    else:                       # 没有
        return END              # → 结束
```

**这就是你手写 `if msg.tool_calls:` 的框架版**——但它是声明式的、可可视化的。

### ⑤ Compile + Invoke

`compile()` 把图编译成可执行对象。然后像 LCEL 一样 `.invoke()` 运行。

---

## 四、`ToolNode` 和 `tools_condition` —— 框架替你写的两个工具

你 Agent L03 手写了 `execute_function`（工具调度器）和 `if msg.tool_calls`（分支判断）。LangGraph 把这两件事预置成了：

| 你手写的 | LangGraph 预置 | 作用 |
|---------|---------------|------|
| `execute_function(name, args)` + `TOOL_REGISTRY` | `ToolNode(tools)` | 自动执行模型请求的工具，把结果变成 ToolMessage 塞回 messages |
| `if msg.tool_calls: ... else: ...` | `tools_condition` | 自动判断"要不要调工具"，返回路由 |

所以你的 `execute_function` + 分支逻辑（约 30 行），在 LangGraph 里是两行：
```python
builder.add_node("tools", ToolNode(tools))
builder.add_conditional_edges("agent", tools_condition)
```

> L07 会讲 `ToolNode` 背后的 `@tool` 装饰器——它自动从函数签名生成 schema，省掉你手写 `TOOLS_SPEC`。

---

## 五、手写循环 vs 图：代码量对比

| 环节 | Agent L03 手写 | LangGraph 图 |
|------|---------------|-------------|
| 工具定义 | 手写 TOOLS_SPEC JSON Schema（~35行）| `@tool` 装饰器（~5行，L07 详讲）|
| 工具执行 | `execute_function` 调度器（~10行）| `ToolNode(tools)`（1行）|
| 分支判断 | `if msg.tool_calls:`（手写）| `tools_condition`（1个函数名）|
| 循环控制 | `for step in range(max_steps)` | 图的回路 `tools → agent`（1条边）|
| 终止判断 | 手动检测 "Final Answer" 字符串 | 走到 `END` 自动终止 |
| 状态管理 | 手动 `messages.append(...)` | State 自动追加 |
| 可视化 | 无 | `graph.get_graph()` 可画图 |

**核心不变的是 ReAct 的原理**（Thought→Action→Observation 循环）——图只是换了一种更结构化、更可扩展的方式来表达同一个循环。

---

## 六、本课代码

`code.py` 做三件事：

1. **用 StateGraph 重写 Agent L03 的 ReAct**（agent + tools 两节点 + 条件边）
2. **对比手写循环**：打印图的结构，看 LangGraph 怎么把 while 循环变成图
3. **多步任务**：跑一个需要多次工具调用的任务（时间+计算），看图怎么自动循环

---

## 七、小结 & 下节预告

✅ 现在你应该明白：
- Agent 本质是状态机，状态机可以用图表达
- StateGraph 三要素：State（状态）、Node（节点=函数）、Edge（边=连线，含条件边）
- `ToolNode` + `tools_condition` 替代了你手写的 `execute_function` + `if tool_calls`
- 图相比 while 循环：可视化、可扩展、可持久化（L08 学）

> ⚠️ **一个清醒认知**：图没有改变 ReAct 的原理（仍然是"调模型→看要不要用工具→执行→喂回去"）。它改变的是**表达方式**——从命令式的"一步步怎么做"变成声明式的"有哪些节点、怎么连线"。原理你 Agent L03 已经懂了，这里只是给它找个更工程化的家。

🔜 **L07** 深入 `@tool` 装饰器和 `create_react_agent` 预置 Agent——把你 Agent L02（TOOLS_SPEC）+ L04（工具设计）的内容完全框架化。学完 L07，"手写 Agent"的每个环节就都有框架对应了。
