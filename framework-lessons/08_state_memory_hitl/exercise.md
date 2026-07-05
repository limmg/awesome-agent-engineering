# Lesson 08 练习 — 状态、记忆与人机协作

> 本课是 LangGraph 的杀手锏。练习重点在第 2、3 题（HITL 是面试加分项）。

---

## 练习 1：体验 thread_id 隔离（5 分钟）

在 `experiment_1_memory` 基础上，连续做 3 轮对话（用同一个 thread_id）：

1. "我叫张三，我喜欢蓝色"
2. "我今天心情不错"
3. "我叫什么？喜欢什么颜色？"

验证第 3 轮能答出"张三"和"蓝色"。

然后换一个**新的 thread_id**，直接问"我叫什么"——确认它答不出。

**思考**：这对应 Agent L05 的什么手写代码？（提示：你手写的 `messages` 列表 + 多用户字典路由）

---

## 练习 2：interrupt 的拒绝路径（核心练习，10 分钟）

`experiment_2` 演示了"批准"路径。现在试**拒绝**路径：

把第 2 次 invoke 改成 `Command(resume="no")`，观察：
1. 工具是否被执行？（应该没有）
2. Agent 收到"用户拒绝了"后，最终回答是什么？

**思考**：这种"被拒绝后 Agent 怎么反应"的交互，手写循环里要怎么实现？为什么不如 interrupt 优雅？

> 进阶：试着让 `call_tools_with_approval` 根据 `approval` 的不同值做不同处理（如 "修改金额" → 让 Agent 重新提方案）。

---

## 练习 3：给金额设审批阈值（实战 HITL，15 分钟）

真实的审批通常有阈值：小额自动放行，大额才问人。改写 `call_tools_with_approval`：

```python
def call_tools_with_approval(state):
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if not tool_calls:
        return {"messages": []}

    # ⭐ 只在金额 >= 阈值时才 interrupt
    THRESHOLD = 500
    for tc in tool_calls:
        if tc["name"] == "spend_money" and tc["args"].get("amount", 0) >= THRESHOLD:
            approval = interrupt({"question": "大额消费，是否批准？", ...})
            if approval != "yes":
                return {"messages": [HumanMessage("用户拒绝了大额消费")]}

    # 小额或已批准 → 正常执行
    return ToolNode(TOOLS).invoke({"messages": state["messages"]})
```

测试：
- "帮我花 50 元买咖啡" → 自动执行（不 interrupt）
- "帮我花 1000 元买耳机" → interrupt 问人

> 这是 HITL 最常见的生产模式：**高风险操作才问人，低风险自动跑**。

---

## 练习 4：用 SqliteSaver 持久化到磁盘（进阶，10 分钟）

`MemorySaver` 进程退出就丢。换成 `SqliteSaver` 持久化到文件：

```bash
pip install langgraph-checkpoint-sqlite
```

```python
from langgraph.checkpoint.sqlite import SqliteSaver
# SqliteSaver 是上下文管理器
with SqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
    # 同样的代码，但现在状态存到了 checkpoints.db 文件
```

测试：跑一轮对话 → 关掉程序 → 重新启动 → 用同 thread_id 问"我叫什么"——**应该还记得**（因为存在文件里了）。

**观察**：换 Checkpointer 类，图的代码一行没改——这就是 Checkpointer 抽象的价值。

---

## 练习 5：对比 Agent L05 的三种记忆策略（认知题，5 分钟）

Agent L05 你手写了三种策略：keep_all / truncate / summary。在 LangGraph 里：

| Agent L05 策略 | LangGraph 里怎么实现？ |
|---------------|---------------------|
| keep_all（全保留）| Checkpointer 默认行为（同 thread_id 全留）|
| truncate（截断）| 在节点函数里加 `state["messages"] = state["messages"][-6:]` |
| summary（摘要）| 加一个"摘要节点"，定期把旧消息压成摘要 |

**思考**：原理变了吗？（答案：没有。框架帮你存档了，但窗口策略的取舍仍在。）

---

## 思考题（不写代码）

1. **为什么 interrupt 需要 Checkpointer？** 没有 Checkpointer，interrupt 暂停后会发生什么？

2. **thread_id 和 Agent L05 的"多用户 messages 字典"是什么关系？** 哪个更优雅？

3. **HITL 在生产环境怎么落地？** 提示：interrupt 暂停 → 存到数据库 → 前端弹审批按钮 → 用户点批准 → 后端 Command(resume) 恢复。

---

## 完成标志

- [ ] 跑通跨轮记忆：同 thread_id 记住、不同 thread_id 失忆
- [ ] 跑通 HITL：interrupt 暂停 → Command(resume) 恢复
- [ ] 体验了拒绝路径（练习 2）
- [ ] 理解 interrupt 为什么需要 Checkpointer
- [ ] 能说清"这比 Agent L05 手写强在哪"

下一课 [L09](../09_capstone/) 毕业项目：用 LangGraph 重做研究助手，综合 L06-L08 全部技术。
