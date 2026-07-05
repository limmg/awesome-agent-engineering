# Lesson 01 练习 — Supervisor 主从模式

> 这是多智能体编排的第一课，练习重点在"理解动态路由"和"对比手写流水线"。

---

## 练习 1：画出星型拓扑（关键概念，5 分钟）

运行 `code.py` 的实验 3，看打印的 Mermaid 图。然后**手画**一张 supervisor 系统的拓扑图（纸笔即可），标注：

- 哪些是 worker？分别叫什么？
- 哪些边是**虚线**（条件边）？为什么是条件边？
- 哪些边是**实线**（固定边）？为什么是固定的？
- supervisor 在哪里？它和每个 worker 的关系是什么？

**对比**：打开 `agent-lessons/08_multi_agent/code.py`，把你的星型拓扑和手写 L08 的流水线画在一起。直观感受"一条直线"vs"星型"的差别。

> 这是面试高频题："Supervisor 多智能体架构是什么？"——能画出星型拓扑并解释"调度中心运行时决定派给谁"，就答得很好。

---

## 练习 2：追踪消息流，看清动态路由（核心机制，10 分钟）

运行 `code.py` 的实验 1（复合任务），代码会打印完整消息流。回答：

1. supervisor 第一次派给了谁？为什么？（看 `transfer_to_xxx` 消息）
2. 第一个 worker 完成后，消息里出现了什么？（提示：`Transferring back to supervisor`）
3. supervisor 收到回传后，第二次派给了谁？
4. 整个任务一共经过了几次"派发→回传"？

**关键观察**：每次 worker 完成都要回 supervisor——这就是 supervisor 模式的"中心化"特征，也是它比 swarm 多花 LLM 调用的原因（L02 会讲 swarm 怎么省掉这个）。

---

## 练习 3：加一个新 worker（10 分钟）

参考现有代码，加一个新 worker：**`summarizer`（摘要员）**，职责是把长文本压成 3 句话摘要。

要求：
1. 用 `create_agent` 创建，**记得传 `name="summarizer"`**（不传会报错，code.py 里特意标了 ⚠️）
2. 写清楚 system_prompt（它该干什么、不该干什么）
3. 在 `create_supervisor` 的 `agents=[...]` 列表里加上它
4. 在 supervisor 的 `prompt` 里告诉它"什么时候派 summarizer"
5. 跑一个需要摘要的任务，比如"帮我查北京天气，然后总结成一句话"

**观察**：加一个 worker 你改了几处？（对比手写 L08 要加一个新 Agent 函数 + 改流水线顺序 + 改通信逻辑）

---

## 练习 4：对比动态调度（认知题，5 分钟）

运行 `code.py` 的实验 2（简单任务"算 12×8"），回答：

1. supervisor 派了几个 worker？分别是谁？
2. 它**跳过**了哪几个 worker？为什么？
3. 如果是手写 L08 的流水线，这个简单任务会走几步？（planner→executor→reviewer 全套）

**核心认知**：这就是 supervisor 相对手写流水线的最大价值——**按需调度**。简单任务只派必要的 worker，省 token 省时间。手写 L08 的写死流程做不到这点。

> 思考：什么情况下"按需调度"省下的成本，能抵消 supervisor 本身的额外 LLM 调用开销？（提示：worker 数量多、任务复杂度差异大时）

---

## 练习 5：手写流水线 vs Supervisor 的代码量（认知题，5 分钟）

数一下两个版本的关键代码行数：

| 环节 | Agent L08 手写（行数）| Supervisor 版（行数）|
|------|---------------------|---------------------|
| Agent 定义（3 个）| ?（planner/executor/reviewer 函数）| ?（3 个 create_agent）|
| 工具定义 | ?（函数+JSON Schema+Registry）| ?（@tool 装饰器）|
| 编排逻辑 | ?（run_multi_agent 的 for 循环）| ?（create_supervisor + compile）|
| 动态路由 | 做不到 | ?（内置，0 行）|
| **总计** | ? | ? |

把数字填进去，亲眼看框架省了多少——而且省的不只是行数，是**能力**（动态路由手写做不到）。

---

## 思考题（不写代码）

1. **Supervisor 模式的"每次回中心"有什么代价？** 如果有 10 个 worker、每个任务要走 5 步，一共要调几次 LLM？（提示：每次派发和回传都过 supervisor）

2. **Supervisor 和手写 L08 的 Planner 有什么本质区别？** 提示：一次性出清单 vs 每步动态决策。

3. **什么时候该用 Supervisor，什么时候该用手写流水线？** 提示：任务流程是否可预测、worker 数量、成本敏感度。

---

## 完成标志

- [ ] 能手画 supervisor 的星型拓扑（调度中心居中 + worker 外围 + 虚线/实线边）
- [ ] 能从消息流里追踪出"派给谁→回传→再派给谁"的动态路由过程
- [ ] 知道 `create_agent` 在多智能体场景**必须传 `name=`**
- [ ] 跑通了"简单任务只派必要 worker"的实验，理解按需调度的价值
- [ ] 理解 supervisor 每次回中心的代价（为 L02 的 swarm 做铺垫）

下一课 [L02](../02_swarm_handoff/) 学 Swarm + Handoff——让 Agent 之间能直接交接，不必每次都回中心。
