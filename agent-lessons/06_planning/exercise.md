# L06 练习

> 改 `code.py` 里的代码，运行 `python agent-lessons/06_planning/code.py` 观察变化。

---

## 练习 1：构造一个 5+ 步骤的任务
换一个更复杂的任务，看 Plan-Execute 的规划能力：

```python
task = "帮我查北京、上海、广州三个城市的天气，找出最热的城市，算最热和最冷的温差，最后给出穿衣建议。"
```

**观察**：计划里有几步？执行时是不是按计划有序完成了？有没有遗漏？

**思考**：对比同样任务用 ReAct 跑——ReAct 会不会中间乱了或漏掉某个城市？这就是预先规划的价值。

---

## 练习 2：让计划可以"动态修改"
当前 Plan-Execute 是"一次性规划、严格执行"。但现实中，执行到一半可能发现计划要调整。试着改进：

```python
def execute_plan_adaptive(client, task, steps):
    """每个步骤执行后，让 LLM 评估'剩余计划是否需要调整'。"""
    for i, step in enumerate(steps):
        # ... 执行当前步骤 ...
        # 执行完后问 LLM：基于刚才的结果，后面的计划还要改吗？
        review = chat(client, [
            {"role": "user", "content": f"已完成：{step}→{result}。剩余计划：{steps[i+1:]}。需要调整吗？只回答'需要调整：xxx'或'不需要'"}
        ])
        if "需要调整" in review:
            # 重新规划剩余步骤
            steps[i+1:] = plan(client, f"基于已完成的{completed}，重新规划：{task}")
```

**思考**：这就是"Plan + ReAct 结合"的雏形——既预先规划，又允许根据执行反馈动态调整。工业级 Agent 常用这种混合模式。

---

## 练习 3：对比 CoT 和 Plan 的区别
CoT（思维链）和 Plan 看起来都是"分步"，但有本质区别。试着用两种方式解同一个问题：

```python
# CoT 方式：让模型直接一步步推理（不输出任务清单）
cot_answer = chat(client, [{"role":"user","content":
    f"请一步步思考：{task}"}])

# Plan 方式：先输出计划再执行（本课的做法）
steps = plan(client, task)
```

**思考**：
- CoT 是"推理分步"（模型脑子里分步想）
- Plan 是"任务分步"（显式列出步骤清单，程序化执行）
- 哪个更可控？哪个更灵活？

---

## 练习 4：计划失败的容错
如果 `plan()` 返回的 JSON 解析失败（模型偶尔输出格式不对），会发生什么？当前代码有个兜底（按行分割），但可能效果不好。

试着改进容错：解析失败时，重新让 LLM 规划一次（最多重试 2 次）：

```python
def plan_with_retry(client, task, max_retries=2):
    for attempt in range(max_retries + 1):
        steps = plan(client, task)
        if steps and isinstance(steps, list):
            return steps
        print(f"规划失败，重试 {attempt+1}/{max_retries}")
    return [task]  # 最终兜底：把整个任务当一步
```

**思考**：生产级 Agent 必须处理"模型输出不可靠"的情况。重试 + 兜底是基本范式。

---

## ✅ 完成本课后，你应该能回答
1. 为什么复杂任务需要规划？边想边做（ReAct）有什么短板？
2. CoT 思维链是什么？它和 Plan 的区别？
3. Plan-and-Execute 的两个阶段分别做什么？
4. 为什么让模型输出 JSON 格式的计划？（提示：可解析、可程序化执行）
5. ReAct 和 Plan-Execute 各自适合什么场景？
