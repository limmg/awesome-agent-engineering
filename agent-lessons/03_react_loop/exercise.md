# L03 练习

> 改 `code.py` 里的代码，运行 `python agent-lessons/03_react_loop/code.py` 观察变化。
> 本课是面试核心，建议反复实验，吃透 ReAct 循环。

---

## 练习 1：构造一个 4+ 步的复杂任务
设计一个需要 Agent 走 4 步以上才能完成的任务，观察完整的推理链：

```python
run_react_agent(client,
    "现在几点？请把当前小时数和分钟数相加，"
    "再用结果除以 7，告诉我余数是多少。"
)
```

**观察**：Agent 应该走：查时间 → 提取小时分钟 → 相加 → 算余数 → 给答案。每一步都有 Thought。

**思考**：如果 Agent 跳过了"提取"这步直接调 calculator，会怎样？（提示：它需要自己把时间里的数字提取出来作为表达式，这就是 Thought 的价值——帮它理清中间步骤）

---

## 练习 2：触发死循环防护
把 `MAX_STEPS` 改成 2，然后问一个需要 3 步以上的问题：

```python
MAX_STEPS = 2
run_react_agent(client, "现在几点？'AI'有几个字？两个数相乘多少？")
```

**观察**：Agent 会在第 2 步被强制停止，打印"达到最大步数"。

**思考**：为什么 max_steps 是 ReAct 的必备设计？（提示：模型可能反复调用同一个工具、或陷入"我还需要更多信息"的死循环）生产环境你该怎么设这个值？（太小提示任务做不完，太大提示可能烧钱）

---

## 练习 3：对比有无 Thought 的效果（核心实验）
这是本课最重要的练习。仔细对比实验 1（ReAct）和实验 2（原生）的输出：

- ReAct 你能看到什么？（Thought: "我需要先..."）
- 原生你能看到什么？（只有 Action 和 Observation）

试着问一个会让 Agent **犯错**的问题（比如故意模糊），看哪种模式更容易发现它错在哪：

```python
run_react_agent(client, "帮我把 'hello world' 的长度和当前的秒数相加")
run_plain_agent(client, "帮我把 'hello world' 的长度和当前的秒数相加")
```

**思考**：当 Agent 给出错答案时，哪种模式更容易定位 bug？这就是 ReAct 在生产调试中的价值。

---

## 练习 4：纯 prompt 版 ReAct（不用 function calling）
本课的 ReAct 借助了 function calling 来执行工具。但真正的"纯 ReAct"是**完全靠 prompt**——让模型直接在文本里输出 `Action: calculator\nAction Input: 2+2`，你自己用正则解析。

试着改造 `run_react_agent`，去掉 `tools` 和 `tool_choice`，改用 prompt 引导：

```python
# 让模型输出这种纯文本格式：
# Thought: 我需要算 2+2
# Action: calculator
# Action Input: {"expression": "2+2"}

# 然后你用正则解析 Action 和 Action Input：
import re
action_match = re.search(r"Action:\s*(\w+)", msg.content)
input_match = re.search(r"Action Input:\s*(\{.*\})", msg.content)
```

**思考**：纯 prompt 版 ReAct 的好处是不依赖模型的 function calling 能力（任何模型都能用）。缺点是什么？（提示：解析容易出错、格式不稳定）

---

## ✅ 完成本课后，你应该能回答（面试高频）

1. ReAct 是什么？两个词分别代表什么？（Reasoning + Acting）
2. ReAct 循环的三个环节是什么？（Thought → Action → Observation）
3. ReAct 相比原生 function calling 的核心优势？（显式思考、可追溯、可调试）
4. 为什么 ReAct loop 要设 max_steps？（防死循环）
5. ReAct 是一种 API 还是 prompt 模式？（关键认知：它是 prompt 设计模式，不是 API）
6. 手写 ReAct loop 的核心结构？（while 循环 + LLM 决策 + 工具执行 + 结果回传）
