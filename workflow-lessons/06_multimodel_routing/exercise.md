# Lesson 06 练习 — 多模型路由与网络拓扑

> 这是 LangGraph 段收官，练习重点在"拓扑选型"和"多模型降本"。

---

## 练习 1：拓扑归类（关键概念，5 分钟）

把前 5 课的场景归类到四种拓扑：

| 场景 | 属于哪种拓扑？ |
|---|---|
| L01 supervisor 调度 researcher/analyst/writer | ? |
| L02 客服 triage→refund→after_sales 直接交接 | ? |
| L03 把客服 swarm 封装成子图嵌入父图 | ? |
| L04 把主题拆 3 份并行查询再合并 | ? |
| 手写 L08 的 planner→executor→reviewer 固定顺序 | ? |

参考答案在 README 的拓扑总览表里。这道题帮你建立"看到需求就知道用什么拓扑"的直觉。

---

## 练习 2：追踪多模型路由的消息流（核心机制，5 分钟）

运行 `code.py` 的实验 2，看消息流里的模型标注：

1. supervisor 用的是哪个模型？调用了几次？
2. analyst 用的是哪个模型？调用了几次？
3. 如果全用 glm-4，成本是现在的几倍？（提示：worker 用 flash 是免费的）

> 这就是多模型路由的价值——执行类 worker 用免费模型，成本大降。

---

## 练习 3：对比全 glm-4 vs 多模型的质量（认知题，10 分钟）

跑两次同一个任务，对比质量：

**第一次**：把 `code.py` 实验 2 的 `fast_llm` 也改成 `glm-4`（全 glm-4）
**第二次**：保持原样（supervisor glm-4 + worker flash）

回答：
1. 两次的最终回答质量差别大吗？
2. 如果 worker 做的是"简单查资料"，flash 够用吗？
3. 如果 worker 做的是"复杂推理分析"，flash 还够用吗？

> 💡 这道题帮你理解多模型路由的前提：执行类任务 flash 能胜任。复杂任务还是得 glm-4。

---

## 练习 4：加一个 reviewer 用 glm-4（10 分钟）

在实验 3 的基础上加一个 **reviewer**（审查者），用 glm-4（审查要准）。

要求：
1. `reviewer = create_agent(smart_llm, tools=[], name="reviewer", ...)`
2. 加到 supervisor 的 agents 列表
3. 在 supervisor 的 prompt 里告诉它"写完文案后派 reviewer 审查"
4. 跑一遍，看消息流：researcher(flash) → writer(glm-4) → reviewer(glm-4)

**观察**：现在有 3 个不同角色的 Agent，各用什么模型？为什么？

> 答案：researcher(flash 查资料)、writer(glm-4 写作)、reviewer(glm-4 审查)。决策/质量类用 glm-4，执行类用 flash。

---

## 练习 5：设计你自己的混合拓扑（进阶，15 分钟）

设计一个"电商客服系统"的拓扑，满足：
- 用户问题先到**分诊 supervisor**（glm-4 决策）
- 客服问题进**客服子图**（内部 swarm：退款/售后/投诉，全用 flash）
- 商品咨询走**并行查询**（多个商品查询 worker 并行，用 flash）
- VIP 用户走**专属通道**（glm-4 全程，质量优先）

画出你的拓扑图（纸笔即可），标注每层用什么模型。

> 这道题考验综合能力——混合拓扑 + 多模型路由。没有标准答案，重点是练"按场景选型"的架构思维。

---

## 思考题（不写代码）

1. **为什么 supervisor 要用 glm-4 而 worker 可以用 flash？** 提示：决策（派给谁）出错会导致整个任务失败；执行（查资料）出错影响较小。

2. **如果 glm-4-flash 完全免费且无限调用，为什么不全用它？** 提示：复杂推理 flash 会翻车；supervisor 的路由决策一旦出错，后面全白费。

3. **四种拓扑里，哪种最适合多模型路由？** 提示：层级拓扑——顶层决策用贵模型，多层往下逐步用便宜模型。

---

## 完成标志

- [ ] 能把前 5 课的场景归类到四种拓扑（星型/网状/层级/流水线）
- [ ] 理解多模型路由：supervisor 用 glm-4，worker 用 flash
- [ ] 知道差异化模型：不同 worker 按任务特点选模型
- [ ] 理解降本逻辑：决策少且贵，执行多且免费
- [ ] LangGraph 主干段（L01-L06）全部掌握 🎓

下一课 [L07](../07_crewai_comparison/) 进入横向框架对比——用 CrewAI 重写同样的系统，对比"角色驱动"vs"图驱动"两种范式。
