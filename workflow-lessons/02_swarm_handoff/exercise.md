# Lesson 02 练习 — Swarm 与 Handoff

> 练习重点在"对比 supervisor 和 swarm 两种拓扑"以及"理解 handoff 是工具调用"。

---

## 练习 1：对比两种拓扑的消息流（关键概念，5 分钟）

运行 `code.py` 的实验 2，仔细对比 Swarm 版和 Supervisor 版的消息流。回答：

1. **Swarm 版**的消息流里有 `transfer_back_to_supervisor` 吗？为什么？
2. **Supervisor 版**的消息流里，refund 干完活之后发生了什么？（提示：看 `Transferring back to supervisor`）
3. 同一个任务，两种拓扑各产生了多少条 AIMessage？差值代表什么？

> 这是理解"去中心 vs 中心化"的最直观方式——亲眼看消息流里有没有"回中心"的步骤。

---

## 练习 2：画出两种拓扑（核心机制，5 分钟）

运行 `code.py` 的实验 3，看打印的两个 Mermaid 图。然后**手画**对比图（纸笔即可）：

- **Swarm 拓扑**：标注哪些 agent 互相连接？有没有中心节点？边的类型（虚线/实线）？
- **Supervisor 拓扑**：supervisor 在哪里？worker 怎么连到它？

**思考**：为什么 swarm 的边全是虚线（条件边），而 supervisor 有实线（固定边）？
（提示：swarm 每个 agent 都可能 handoff 给别人；supervisor 的 worker 一定会回到中心）

---

## 练习 3：加一个新 Agent 并接入 handoff（10 分钟）

给客服系统加一个新 Agent：**`complaint`（投诉专员）**，负责处理用户投诉。

要求：
1. 用 `create_agent` 创建，`name="complaint"`
2. 给它配 handoff 工具：能转给 `after_sales`（投诉处理完转售后跟进）
3. 给 `triage` 增加一个 `create_handoff_tool(agent_name="complaint")`（让分诊员能把投诉转过去）
4. 在 `triage` 的 system_prompt 里告诉它"投诉转 complaint"
5. 跑一个投诉任务，比如"我对订单 123 的服务不满意，要投诉"

**观察**：消息流里 triage 是怎么把投诉转给 complaint 的？complaint 处理完又转给了谁？

**踩坑预警**：如果你忘了给 triage 配 `create_handoff_tool(agent_name="complaint")`，triage 就没法转交——会自己硬处理或卡住。这就是 handoff 工具"必须显式配置"的特点。

---

## 练习 4：对比 handoff 和字符串拼接（认知题，5 分钟）

打开 `agent-lessons/08_multi_agent/code.py` 找到这行：

```python
task = f"{task}\n（上一轮审查意见：{verdict}，请改进）"
```

回答：
1. 手写 L08 用这种方式传递信息，有什么风险？（提示：信息截断、格式混乱、上下文丢失）
2. swarm 的 handoff 传递的是什么？（提示：完整对话历史 + 控制权）
3. 哪种更可靠？为什么？

> 这道题帮你理解"为什么需要框架"——字符串拼接是"手搓"，handoff 是"工程化"。

---

## 练习 5：故意制造一个死循环（进阶，10 分钟）

swarm 没有中心调度，如果两个 Agent 的 prompt 设计成"互相推诿"，可能死循环。试试：

把 `refund` 的 system_prompt 改成："你不是退款专员，所有退款问题都转给 after_sales"，
同时把 `after_sales` 的 system_prompt 改成："退款不归我管，转给 refund"。

跑一个退款任务，观察会发生什么。（可能需要按 Ctrl+C 中断）

**思考**：
- supervisor 系统会这样死循环吗？为什么？（提示：supervisor 有中心把关，会判断"都转了几次了还没解决"）
- 这道题揭示了 swarm 的什么风险？（提示：去中心化的代价是缺乏全局控制）

> ⚠️ 这个练习会真实触发死循环（或达到 recursion_limit 报错），这正是 swarm 的真实风险。生产环境一定要设 `recursion_limit` 或加防环机制。

---

## 思考题（不写代码）

1. **Swarm 和 Supervisor 分别像什么现实场景？** 提示：swarm 像"前台→科室→药房"的医院分诊（各自知道下一步）；supervisor 像"项目经理调度多个开发"（中心决策）。

2. **为什么 swarm 必须传 `default_active_agent`，而 supervisor 不用？** 提示：谁负责"第一个接用户"？

3. **如果一个客服系统有 20 个专员，用 swarm 还是 supervisor？** 提示：20 个 agent 两两 handoff 的连接数会爆炸（N²），中心化可能更可控。

---

## 完成标志

- [ ] 能从消息流里区分 swarm（无"回中心"）和 supervisor（有"回中心"）
- [ ] 知道 `create_swarm` 必传 `default_active_agent`（对比 supervisor 不用）
- [ ] 理解 handoff 本质是工具调用（`transfer_to_xxx`），LLM 可以选择不调
- [ ] 能画出网状（swarm）vs 星型（supervisor）的拓扑对比
- [ ] 理解 swarm 的死循环风险（为 L03 子图的模块化控制做铺垫）

下一课 [L03](../03_subgraph/) 学子图 Subgraph——把 swarm/supervisor 系统打包成一个节点，管理复杂度。
