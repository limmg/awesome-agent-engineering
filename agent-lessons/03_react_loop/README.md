# L03 — ReAct：思考-行动-观察循环（面试核心）

> 本课目标：**手写一个最小 ReAct loop（不用任何框架）**。这是 Agent 面试的核心考点——面试官最爱问"你手写过 ReAct loop 吗"，能讲透它比只会调框架值钱得多。
>
> L01/L02 的 Agent 用原生 function calling，决策是"隐式"的。ReAct 把决策过程**显式化**：让模型每步都先想再做再看结果。

---

## 1. 为什么需要 ReAct？

回顾 L02 的 Agent：你给它工具，它调用，你回传结果，它再决策。但这个过程有个问题——**模型的"思考"是黑盒**。

你不知道模型**为什么**选这个工具、**为什么**传这个参数。如果它选错了，你只知道"结果不对"，但不知道它是哪一步想歪的。

ReAct（**Rea**soning + **Act**ing）的思想：**强制模型把每一步的"思考过程"写出来**。这样：
- ✅ 决策可追溯（出错了能看到是哪步想错）
- ✅ 推理更准确（写出来的思考比隐式的更严谨）
- ✅ 便于调试和优化

> 🎯 **核心认知**：ReAct 不是新工具或新 API，它是一种 **prompt 设计模式**——用特定的提示词格式，让模型按"想→做→看"循环工作。

---

## 2. ReAct 循环：Thought → Action → Observation

ReAct 的核心是这个循环：

```
┌─────────────────────────────────────────────┐
│  Thought（思考）：分析当前情况，决定下一步    │
│  "用户问北京天气，我需要调用 get_weather"     │
├─────────────────────────────────────────────┤
│  Action（行动）：执行选定的工具               │
│  调用 get_weather(city="北京")               │
├─────────────────────────────────────────────┤
│  Observation（观察）：看工具返回的结果         │
│  "北京：晴，25°C"                            │
├─────────────────────────────────────────────┤
│  → 回到 Thought，基于观察决定下一步           │
│  "拿到天气了，用户的问题已解决，输出最终答案"  │
└─────────────────────────────────────────────┘
        │
        ▼ （循环直到 Final Answer）
```

一个完整的 ReAct 对话长这样：

```
Thought 1: 用户问"北京天气和2+2"。我需要两步：查天气、算加法。
Action 1: get_weather(city="北京")
Observation 1: 北京：晴，25°C

Thought 2: 天气拿到了。现在算 2+2。
Action 2: calculator(expression="2+2")
Observation 2: 4

Thought 3: 两个信息都拿到了，可以回答用户了。
Final Answer: 北京今天晴，25度；2+2=4。
```

**关键点**：每一轮 Thought 都基于之前的 Observation（观察），形成推理链。

---

## 3. ReAct vs 原生 Function Calling

| | 原生 Function Calling（L01/L02）| ReAct（本课）|
|---|---|---|
| 决策方式 | 模型隐式决策 | **显式输出 Thought** |
| 可追溯性 | 黑盒（不知道为啥这么选）| 白盒（每步思考可见）|
| 实现方式 | SDK 原生支持 | **prompt 引导模型按格式输出** |
| 适合场景 | 简单任务、单步调用 | **复杂任务、多步推理** |
| 依赖 | 依赖模型的 function calling 能力 | 纯 prompt，任何模型都行 |

> 💡 **一个反直觉的点**：ReAct 其实**不需要 function calling API**。它纯靠 prompt 让模型按 `Thought/Action/Observation` 格式输出，你自己解析。本课为了稳健，会**结合两者**——用 function calling 执行工具，但用 ReAct 的 prompt 让模型显式思考。

---

## 4. 手写 ReAct Loop 的关键设计

一个 ReAct loop 本质就是一个 while 循环：

```python
def react_loop(question, max_steps=5):
    for step in range(max_steps):
        # ① 让模型输出 Thought + Action（或 Final Answer）
        thought, action = llm_decide(...)

        # ② 如果是 Final Answer，结束
        if action is FINAL:
            return thought

        # ③ 否则执行 Action，得到 Observation
        observation = execute(action)

        # ④ 把这一轮的 Thought/Action/Observation 加进历史，进入下一轮
        history += [thought, action, observation]
```

### 几个必须处理的工程问题

| 问题 | 解决方案 |
|------|---------|
| 模型无限循环 | 设 `max_steps`（如 5），到上限强制停 |
| 模型不按格式输出 | prompt 里给严格的格式示例 + 解析时兜底 |
| 工具执行失败 | Observation 返回错误信息，让模型看到后调整 |
| 何时算完成 | 模型输出 "Final Answer" 或不再调用工具 |

---

## 5. 本课代码会做什么

`code.py` **完全手写一个 ReAct loop**，不用 LangChain 等任何框架：

### ① ReAct prompt 设计
写一个 system prompt，要求模型按 `Thought / Action / Action Input / Final Answer` 格式输出。

### ② 循环体
一个 while 循环，每轮：调 LLM → 解析它输出的 Thought + Action → 执行工具得到 Observation → 喂回去。

### ③ 打印完整推理链
**每一步都打印** Thought / Action / Observation——你会**亲眼看到 Agent 的完整思考过程**。这是 ReAct 最有价值的部分。

### ④ 实验对比
- 实验 1：一个多步任务，看完整的 Thought→Action→Observation 链
- 实验 2：对比 ReAct 和 L02 的原生 function calling，体会可追溯性的差异

---

## 6. 跑起来

```bash
python agent-lessons/03_react_loop/code.py
```

终端会打印 Agent 每一步的 Thought（思考）/ Action（行动）/ Observation（观察）。重点看：**你能看懂 Agent 为什么这么做**——这就是 ReAct 相比原生 function calling 的核心价值。

---

下一课 [L04 — 多工具与工具设计](../04_tool_design/) 会讲：怎么设计好用的工具，让模型选得准。
