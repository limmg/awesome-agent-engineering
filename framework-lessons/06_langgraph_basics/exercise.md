# Lesson 06 练习 — StateGraph 重写 ReAct

> 这是进入 LangGraph 的第一课，练习重点在"理解图的结构"和"对比手写循环"。

---

## 练习 1：画出你的图（关键概念，5 分钟）

运行 `code.py` 的部分②，看打印的节点和边。然后**手画**一张你这张图的草图（纸笔即可），标注：
- 哪里是节点？分别叫什么？
- 哪里是条件边？条件是什么？
- 哪里是回路？为什么需要回路？

**对比**：打开 `agent-lessons/03_react_loop/code.py`，把图和你手写的 `run_react_agent` 的每一行对应起来（哪个节点 = 哪段代码、哪条边 = 哪个 if）。

> 这是面试高频题："用 LangGraph 怎么实现 ReAct？"——能画出这张图并解释数据流，就答得很好。

---

## 练习 2：理解 State 的自动追加（核心机制，10 分钟）

`MessagesState` 的 messages 字段是"自动追加"的（不是覆盖）。验证这一点：

在 `create_agent_node` 的 `call_model` 里加一行打印，看每次进入节点时 state 里有几条 messages：

```python
def call_model(state):
    print(f"  [agent节点] 收到 {len(state['messages'])} 条 messages")
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}
```

跑多步任务，观察：每经过一次 `tools → agent` 回路，messages 数量怎么变化？

**思考**：如果你返回 `{"messages": [response]}` 但 State 是"覆盖"而非"追加"，会发生什么？（这就是为什么 `MessagesState` 要用 `Annotated[list, add_messages]`）

---

## 练习 3：加一个新工具（10 分钟）

参考 Agent L04 的工具设计，加一个 `get_weather(city: str)` 工具（模拟数据即可），接到图里。然后问"北京和上海天气怎么样"。

要求：
1. 用 `@tool` 装饰器定义（docstring 写清楚何时用）
2. 加进 `TOOLS` 列表（注意：图编译前加）
3. 跑图，看模型是否调用新工具

**观察**：加一个工具，你改了几处？（对比 Agent L03 手写时要同时改 TOOLS_SPEC + TOOL_REGISTRY + execute_function）

---

## 练习 4：对比终止机制（5 分钟）

回答：
1. Agent L03 手写版怎么判断"该结束了"？（提示：检测字符串 "Final Answer"）
2. LangGraph 图怎么判断"该结束了"？（提示：条件边返回 END）
3. 哪种更可靠？为什么？（提示：字符串检测的脆弱性 vs 结构化的路由）

---

## 练习 5：手写循环 vs 图的代码量（认知题，5 分钟）

数一下两个版本的关键代码行数：

| 环节 | Agent L03 手写（行数）| LangGraph 图（行数）|
|------|---------------------|---------------------|
| 工具定义（schema）| ?（TOOLS_SPEC）| ?（@tool）|
| 工具执行调度 | ?（execute_function）| ?（ToolNode）|
| 循环 + 分支 | ?（for + if）| ?（add_edge + 条件边）|
| 状态管理 | ?（messages.append）| ?（State 自动）|

把数字填进去，亲眼看框架省了多少。

---

## 思考题（不写代码）

1. **为什么说"Agent 本质是状态机"？** 一个状态机需要哪些要素？（状态、转移、终止）对应到 LangGraph 是什么？

2. **图的回路 `tools → agent` 和 while 循环的 `continue` 有什么区别？** 提示：声明式 vs 命令式、可视化。

3. **`tools_condition` 帮你省了什么？** 如果没有它，你要怎么写条件边的路由函数？

---

## 完成标志

- [ ] 能手画 StateGraph 的图结构（节点+边+回路）
- [ ] 能把图的每个环节对应回 Agent L03 的手写代码
- [ ] 理解 State 的"自动追加"机制
- [ ] 跑通了多步任务，看到图自动循环多轮
- [ ] 理解"图改变表达方式，不改变 ReAct 原理"

下一课 [L07](../07_tools_and_agents/) 深入 `@tool` 装饰器 + `create_react_agent` 预置 Agent。
