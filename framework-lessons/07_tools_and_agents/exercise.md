# Lesson 07 练习 — Tools + prebuilt Agents

> 本课把工具定义和 Agent 组装完全框架化。练习重点是"理解 @tool 省了什么"和"预置 vs 手写的取舍"。

---

## 练习 1：对比 @tool 和手写 TOOLS_SPEC（核心认知，10 分钟）

打开 `agent-lessons/04_tool_design/code.py`，找到 `TOOLS_SPEC_GOOD` 里的 `get_weather`（约 6 行 JSON）。

在本课 code.py 里用 `@tool` 定义同一个 `get_weather`，然后打印 `get_weather.args_schema.model_json_schema()`。

**对比**：
1. 手写 JSON Schema 和 @tool 自动生成的，内容是否一致？
2. 哪个写起来快？哪个改起来方便（比如加个参数）？
3. 数一下：Agent L04 的 6 个工具，手写 TOOLS_SPEC 共多少行？用 @tool 共多少行？

> 这就是"消灭三份副本"的直观感受。

---

## 练习 2：把 Agent L09 的 web_search 用 @tool 重写（10 分钟）

`agent-lessons/09_capstone/code.py` 里有一个 `web_search` 函数（用 DuckDuckGo）。把它用 `@tool` 装饰器重写：

```python
@tool
def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索信息。当需要查找最新资讯、文档、事实时使用。

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数
    """
    # ... 原来的实现
```

然后接到 `create_agent` 里，问一个需要联网的问题。

**观察**：加一个工具，你只改了几处？（对比 Agent L04 手写时要同时改 TOOLS_SPEC + TOOL_REGISTRY + execute_function）

---

## 练习 3：预置 vs 手写图（关键取舍，10 分钟）

`create_react_agent` 是 L06 手写图的封装。验证这一点：

1. 用 `create_agent` 创建一个 Agent
2. 打印它的图结构：`print(agent.get_graph().nodes)` 和 `print(agent.get_graph().edges)`
3. 对比 L06 你手写的图（也是 agent + tools + 条件边 + 回路）

**确认**：预置版的内部结构和 L06 手写版是否一致？（应该都是 START→agent→(条件)→tools→agent→END）

> 这验证了"create_agent 就是 L06 那张图"——它不是魔法，是封装。

---

## 练习 4：体验"description 仍是灵魂"（10 分钟）

定义两个功能重叠的工具，但 description 写得模糊（学 Agent L04 的坏例子）：

```python
@tool
def string_op_a(text: str) -> str:
    """处理字符串。"""          # 模糊
    return f"长度是 {len(text)}"

@tool
def string_op_b(text: str) -> str:
    """处理字符串。"""          # 和 a 重叠
    return text[::-1]
```

问 Agent："帮我把 hello 反转"。观察模型选了 a 还是 b（可能选错）。

然后把 `string_op_b` 的 docstring 改清楚（`"""把字符串反转（倒序）。"""`），重跑，看是否选对。

**结论**：@tool 没降低 description 的重要性——Agent L04 的教训在框架里完全适用。

---

## 练习 5：何时该手写图（进阶思考，5 分钟）

`create_agent` 够用于标准 ReAct。但如果你想加一个**"自我审查"节点**（agent 回答后，审查节点检查答案是否合理，不合理就回到 agent 重答），预置版做不了。

画一张这个"带审查的 Agent"的图（纸笔即可），标注：
- 需要哪些节点？（agent / tools / reviewer / ...）
- 哪些边？哪个是条件边？

> 这就是"何时该手写 StateGraph 而非用预置"——L09 毕业项目会用到。

---

## 思考题（不写代码）

1. **@tool 从哪些信息源自动生成 schema？** 如果一个参数没有类型注解（只写 `def f(x):`），会发生什么？

2. **`create_agent` 和 L06 手写的 StateGraph，本质区别是什么？** （提示：没有本质区别，一个是另一个的封装）

3. **为什么说"description 是灵魂"？** 框架帮你生成了 schema，但什么部分框架帮不了你？

---

## 完成标志

- [ ] 能说清 @tool 消灭了"哪三份副本"
- [ ] 跑通 create_agent，理解它 = L06 的图
- [ ] 亲眼见过 LLM 用工具犯错（^ vs **），理解 description 的重要性
- [ ] 知道何时用预置 / 何时手写图

下一课 [L08](../08_state_memory_hitl/) 进入 LangGraph 杀手锏：状态持久化 + 人机协作。
