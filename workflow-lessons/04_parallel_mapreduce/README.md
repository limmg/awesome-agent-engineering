# Lesson 04 — 并行执行与 Map-Reduce：fan-out 爆发

> **本课定位**：前三课的所有图都是**串行**的（一个节点完再下一个）。但很多任务天然可以**并行**——同时查 3 个子问题、同时处理 3 份文档。本课用 LangGraph 的 `Send` API 实现 **fan-out（爆发）+ map-reduce（合并）**，这是兑现 Agent L08 README 明确提到的「无法并行」遗憾。
>
> **映射的手写课**：`agent-lessons/08_multi_agent`（手写 L08 的 `executor` 用 `for step in range(6)` **串行**逐步执行——README 里明确说「无法并行」，本课解决这个问题）。

---

## 一、先回顾：你 Agent L08 为什么无法并行？

打开 `agent-lessons/08_multi_agent/code.py`，看 executor：

```python
def executor(client, task, steps):
    messages = [...]
    for step in range(6):                      # ← 串行循环
        resp = client.chat.completions.create(...)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                result = execute_function(...)  # ← 一个接一个执行
```

这是 `for` 循环——**一个完成才开始下一个**。如果 3 个子问题各需 2 秒，串行要 6 秒。

L08 的 README 里明确承认了这个局限：「多 Agent = 关注点分离。但代价是成本和复杂度翻倍」「无法并行」。

**为什么手写难并行？** 因为 Python 的 `for` 循环天然串行，要并行得用 `asyncio` / `threading` 手写并发控制——复杂度暴增。LangGraph 的 `Send` API 把这个复杂性封装了：**声明式地返回多个 Send，框架自动并行执行**。

---

## 二、核心思想：Map-Reduce 模式

### 什么是 Map-Reduce？

源自大数据的经典模式（Hadoop），三个阶段：

```
        map（拆分）           fan-out（并行）         reduce（合并）
大任务 ──────────→ [子任务1, 子任务2, 子任务3] ──────────→ 最终结果
                        ↓          ↓          ↓
                    worker(并行) worker(并行) worker(并行)
                        ↓          ↓          ↓
                    [结果1]    [结果2]    [结果3] ──→ 合并
```

| 阶段 | 做什么 | 对应本课 |
|---|---|---|
| **map** | 把大任务拆成 N 个子任务 | `split` 节点：主题 → 3 个子问题 |
| **fan-out** | N 个 worker **同时**处理 | `Send` 返回 3 个 → 3 个 worker 并行 |
| **reduce** | 合并 N 个结果 | `reduce` 节点：3 个答案 → 1 份报告 |

### 串行 vs 并行（时间对比）

```
串行（手写 L08 的 for 循环）：
  worker1 ▓▓▓  worker2 ▓▓▓  worker3 ▓▓▓   总时间 = 3 × 单任务

并行（Send fan-out）：
  worker1 ▓▓▓
  worker2 ▓▓▓      总时间 ≈ 1 × 单任务（同时跑）
  worker3 ▓▓▓
```

本课实验 2 实测：3 个子问题，**串行 2.3s vs 并行 1.0s，加速 2.3 倍**。

---

## 三、关键 API：`Send` + reducer

### 1. `Send` —— 触发并行 fan-out

`Send` 是 LangGraph 的特殊类型，表示"派一个节点实例去处理这段数据"。**条件边返回多个 Send = 并行**：

```python
from langgraph.types import Send

def route_to_workers(state):
    # 返回 3 个 Send → 框架同时启动 3 个 worker 实例（并行！）
    return [
        Send("worker", {"subtask": "子问题1", "topic": state["topic"]}),
        Send("worker", {"subtask": "子问题2", "topic": state["topic"]}),
        Send("worker", {"subtask": "子问题3", "topic": state["topic"]}),
    ]

builder.add_conditional_edges("split", route_to_workers)
```

`Send` 两个参数：
- `node`：派给哪个节点（这里是 `"worker"`）
- `arg`：传什么数据给这个 worker 实例（这里是子问题）

> 💡 **对比手写 L08**：手写是 `for subtask in steps: result = executor(subtask)`（串行循环）。这里 `return [Send(...) for subtask in steps]`（并行派发）。一行之差，性能天壤之别。

### 2. reducer —— 并行结果合并（关键！）

多个 worker 并行写回**同一个字段**时，必须配 **reducer**，否则会互相覆盖：

```python
import operator
from typing import Annotated

class ResearchState(TypedDict):
    results: Annotated[list[str], operator.add]  # ⭐ operator.add = reducer
    # 没有 Annotated[list, operator.add] 的话，后写的 worker 会覆盖先写的！
```

**reducer 怎么工作？** 每次 worker 返回 `{"results": [某结果]}`，框架不是覆盖 `results`，而是调用 `operator.add(当前results, 新结果)` ——即列表拼接。所以 3 个 worker 各返回一个结果，最终 `results` 是 3 个结果的拼接。

> ⚠️ **铁律：被并行写回的字段，必须配 reducer。** 这是 LangGraph 并行的第一原则，忘了就会丢数据（验证时踩过这个坑——reduce 节点如果不小心又写了 `results`，会重复追加）。本课实验 3 专门演示这个机制。

### 3. worker 的 State（和主图不同）

注意：`Send` 传给 worker 的 `arg` 可以是**任意 dict**，不必和主图 State 一样：

```python
class WorkerInput(TypedDict):
    subtask: str    # worker 只收一个子问题
    topic: str      # + 主题上下文

def worker(state: WorkerInput):  # worker 收的是 WorkerInput，不是 ResearchState
    ...
    return {"results": [result]}  # 但返回时写的是主图的字段（results）
```

这让 worker 可以"只看自己需要的数据"，不用关心主图的其他字段。

---

## 四、本课的架构：并行研究系统

```
                ┌─────────────────────────────────────────┐
START → split ──┤ (Send ×3) ├──→ worker(子问题1) ──┐      │
                │            ├──→ worker(子问题2) ──┼── reduce → END
                │            ├──→ worker(子问题3) ──┘      │
                └─────────────────────────────────────────┘
                 map(拆分)      fan-out(并行)        reduce(合并)
```

- `split`：LLM 把主题拆成 3 个子问题
- `route_to_workers`：返回 3 个 `Send`，触发 3 个 worker **并行**
- `worker ×3`：同时处理（每个调一次 LLM）
- `reduce`：等所有 worker 完成，合并成报告

---

## 五、框架替你做了什么？

| 手写 L08（串行）| 本课（并行 map-reduce）|
|---|---|
| `for step in range(6)` 串行循环 | `Send` 声明式并行，框架自动调度 |
| 3 个子任务串行约 6 秒 | 3 个并行约 2 秒（墙钟时间）|
| 手写并发要 `asyncio`/`threading`，复杂度暴增 | 框架封装了并发控制，只写 `Send` |
| 多个结果手动收集 `collected.append(...)` | reducer(`operator.add`) 自动拼接 |
| 没有自动"等所有完成再合并" | `worker → reduce` 边自动等所有并行 worker 完成 |

**并行的代价**：LLM 调用次数不变（还是 3 次），省的是**墙钟时间**（等待时间）。如果 LLM API 有并发限制（QPS），并行可能触发限流——这是生产环境要注意的。

---

## 六、并行不是银弹：什么时候用？

**适合并行**：
- 子任务**互相独立**（查 3 个不同问题，互不依赖）
- 每个子任务**耗时相当**（避免"一个慢拖累全部"）
- 对**延迟敏感**（用户等不了 15 秒，但能等 5 秒）

**不适合并行**：
- 子任务**有依赖**（B 需要 A 的结果——只能串行）
- 子任务**极快**（并行的调度开销 > 节省的时间）
- **成本敏感**（并行不省钱，只省时间）

> ⚠️ **reduce 瓶颈**：reduce 节点必须等**所有**并行 worker 完成才开始。如果 3 个 worker 里有一个特别慢，reduce 会被它卡住。这时考虑加超时或用"最快 N 个"策略。

---

## 七、本课代码

`code.py` 做三件事：

1. **实验 1（完整并行 map-reduce）**：主题 → LLM 拆分 → 3 个 worker 并行查询 → reduce 合并报告。实测并行加速。
2. **实验 2（串行 vs 并行对比）**：同样的 3 个子问题，分别用 for 循环（串行）和 Send（并行）跑，亲眼看耗时差异（约 2-3 倍加速）。
3. **实验 3（reducer 机制）**：图解演示"没有 reducer 会覆盖，有 reducer 会拼接"——并行第一铁律。

```bash
python workflow-lessons/04_parallel_mapreduce/code.py
```

---

## 八、小结 & 下节预告

**✅ 本课要点**：
- `Send(node, arg)` 触发并行：条件边返回 `[Send, Send, ...]` = fan-out
- reducer(`operator.add`) 合并：并行结果自动拼接，不覆盖
- map-reduce 三阶段：split（拆）→ worker×N（并行）→ reduce（合）
- 并行省**墙钟时间**（2-3 倍加速），但 LLM 调用次数不变
- 铁律：被并行写回的字段**必须**配 reducer，否则丢数据
- 对比手写 L08：`for` 循环串行 → `Send` 并行（兑现「无法并行」遗憾）

**🔜 下节预告（L05 — 共享状态通信）**：
到目前为止，Agent 之间要么靠 handoff 传消息（L02），要么靠 Send 传子任务（本课）。但很多时候多个 Agent 要**读写同一块共享数据**。L05 深入讲三种通信机制：消息传递（手写 L08 的字符串拼接）、共享 State（本课的 reducer 字段）、黑板模式——以及什么时候用哪种。

> ⚠️ **清醒认知**：并行不省钱（LLM 调用次数不变），只省时间。而且它引入了新的复杂度（reducer、并发限制、reduce 瓶颈）。3 个子任务用并行很爽，30 个子任务可能把 API 打爆。生产环境一定要加并发度控制。
