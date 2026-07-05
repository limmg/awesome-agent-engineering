# Lesson 04 练习 — 并行执行与 Map-Reduce

> 练习重点在"理解 Send 触发并行"和"reducer 的合并机制"。

---

## 练习 1：追踪并行执行（关键概念，5 分钟）

运行 `code.py` 的实验 1，观察输出顺序。回答：

1. `[worker] ✓ 完成一个子问题` 这行打印了几次？它们是同时完成的还是一个个完成的？
2. `[reduce]` 是在所有 worker 都完成后才出现的吗？为什么？（提示：reduce 等所有并行分支汇合）
3. 如果把 `route_to_workers` 里的 `Send` 从 3 个减到 1 个，会发生什么？（提示：退化成串行单任务）

> 这是理解"并行"的最直观方式——亲眼看多个 worker 同时跑、reduce 等全部完成。

---

## 练习 2：对比串行 vs 并行的耗时（核心机制，5 分钟）

运行 `code.py` 的实验 2，记录数据：

| | 串行耗时 | 并行耗时 | 加速比 |
|---|---|---|---|
| 你的实测 | ?s | ?s | ?x |

**思考**：
1. 为什么并行大约是串行的 1/N 时间（N=子任务数），而不是精确的 1/N？（提示：并行调度有开销，且 reduce 要等最慢的）
2. 如果把子任务从 3 个增加到 10 个，加速比会怎么变？（提示：受 API 并发限制影响）

---

## 练习 3：故意去掉 reducer（关键认知，5 分钟）

这是理解 reducer 的最佳方式。把 `ResearchState` 里的：

```python
results: Annotated[list[str], operator.add]   # 有 reducer
```

改成：

```python
results: list[str]   # 没有 reducer
```

再跑实验 1，观察 `results` 最终有几个元素。

**预期**：没有 reducer，多个并行 worker 的返回会**互相覆盖**，最终 `results` 只有 1 个元素（最后一个完成的 worker 的结果）。

> ⚠️ 这就是为什么"被并行写回的字段必须配 reducer"——忘了就丢数据。改完验证后记得改回来。

---

## 练习 4：改并行度（10 分钟）

在 `make_split_node` 里，把 LLM 的提示从"拆成 3 个"改成"拆成 5 个"，并把 `subs[:3]` 改成 `subs[:5]`。

跑实验 1，观察：
1. 现在有几个 worker 并行？
2. 耗时和 3 个 worker 时差不多，还是明显变长？（提示：如果差不多，说明并行度足够；如果变长，可能触发了 API 并发限制）

**思考**：并行度是不是越大越好？（提示：API 有 QPS 限制，太大会被限流甚至报错）

---

## 练习 5：加一个"最慢 worker"观察 reduce 瓶颈（进阶，10 分钟）

在 worker 节点里加一个随机延迟，模拟"某个子任务特别慢"：

```python
import random, time
def worker(state):
    delay = random.uniform(0.5, 3.0)   # 随机延迟 0.5~3 秒
    time.sleep(delay)
    print(f"  [worker] 延迟 {delay:.1f}s 后完成")
    ...
```

跑几次，观察：
1. reduce 是在**最快的** worker 完成后开始，还是**最慢的**完成后开始？
2. 如果一个 worker 延迟 3 秒，其他都 0.5 秒，总时间约多少？（提示：约 3 秒——reduce 被最慢的卡住）

> 这就是"reduce 瓶颈"——并行系统总时间取决于**最慢的**那个任务。生产环境要加超时或容错。

---

## 思考题（不写代码）

1. **Send 和 supervisor 的 handoff 有什么区别？** 提示：handoff 是"转交控制权"（一次一个），Send 是"同时派多个"（并行）。

2. **为什么 reduce 必须等所有 worker 完成？** 如果只等前 2 个就合并，会有什么问题？（提示：数据不完整；但有些场景可以接受"近似结果"，比如只要 3 个里的 2 个答案就够了）

3. **map-reduce 和 L01 的 supervisor 都有"分发"，区别在哪？** 提示：supervisor 串行派（一次一个），map-reduce 并行派（一次 N 个）。

---

## 完成标志

- [ ] 看到多个 worker 并行执行（不是排队串行）
- [ ] 实测了串行 vs 并行的加速比（约 2-3 倍）
- [ ] 理解 reducer 的作用（去掉会丢数据）
- [ ] 知道 `Send(node, arg)` 触发 fan-out 的机制
- [ ] 理解 reduce 瓶颈（等最慢的 worker）

下一课 [L05](../05_shared_state/) 学共享状态通信——多 Agent 怎么交换信息（消息/共享态/黑板三种机制）。
