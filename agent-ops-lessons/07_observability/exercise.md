# L07 练习

> 改 `code.py` 或 research-assistant 的代码，运行观察变化。本课零外部依赖。

---

## 练习 1：设计实验——告警阈值怎么设（设计实验类）

`alert_steps_high` 设多少？太紧正常任务告警（狼来了），太松卡死了才发现。

1. **假设**：告警阈值应 < 截断阈值（L01 的 max_total_steps），实现「先告警再截断」。
2. **实验设计**：
   - 在 `code.py` 跑 `demo_six_faults_summary`，看 loop 场景的步数（11）。
   - 设 `alert_steps_high` = 8 / 11 / 15 / 25，看哪些值会让 loop 场景告警。
   - 找到「正常不告警、故障能告警」的区间。
3. **预期**：loop 步数 11，所以 alert_steps_high 应 ≤ 11 才能告警 loop。但 pure 步数 7，所以 alert_steps_high > 7 才不误告警 pure。区间是 (7, 11]。
4. **思考**：为什么默认 alert_steps_high=25 而 max_total_steps=30？（提示：25 < 30，先告警（25）再截断（30），给运维反应时间。）

**验收**：给出 alert_steps_high 推荐值，说清和 max_total_steps 的联动关系（告警 < 截断）。

---

## 练习 2：扩展 run summary 字段（方法练习）

现状 run summary 没有记录「重写次数」和「补研次数」。

1. 在 `RunSummary` 加 `rewrite_count` 和 `re_research_count` 字段。
2. 在 `build_summary` 从 state 提取（`state.get("rewrite_count", 0)`）。
3. 加一个告警：重写次数 ≥ max_rewrites 时告警「⚠️ 打回次数到上限，报告质量可能差」。
4. 跑测试验证。

**验收**：新字段出现在 summary 行里；重写到上限时触发告警。

---

## 练习 3：思考题——run summary 和 frontier-L08 评估能复用分析脚本吗（理解类）

字段设计对齐了，但语义不同（健康 vs 质量）。

1. **思考**：哪些字段是两者共有的？（提示：步数、token、循环检测、降级。）
2. **思考**：哪些字段是各自独有的？（提示：评估有「任务成功率/失败归因」（质量），观测有「熔断状态/审批等待/恢复」（健康）。）
3. **结论**：用一句话说清「字段对齐」的好处（同一套分析脚本能处理两类数据），以及为什么语义不能混（健康指标实时告警，质量指标事后评估）。

**验收**：能列出共有字段和独有字段，说清对齐的收益（复用脚本）和语义不能混的原因。

---

## 绋试 4：思考题——为什么不能只靠 ops 的 tracing 看 Agent 健康（取舍类）

ops-L02 已经接了 Langfuse tracing，能看到每一步的 span 树。为什么还要 run summary？

1. **思考**：tracing 看的是 span（单步），run summary 看的是运行级聚合。一个 30 步的 Agent 跑，tracing 有 30 个 span，怎么一眼看出「这次跑得健康」？（提示：要聚合，span 本身不聚合。）
2. **思考**：告警怎么从 span 触发？（提示：很难——span 是细粒度的，要在 span 上做聚合查询才能发现「步数过高」。run summary 把聚合预先算好，告警直接查一个字段。）
3. **结论**：用一句话说清 tracing 和 run summary 的分工（tracing 看细节，summary 看聚合），以及为什么两者都要。

**验收**：能说清 tracing（span 细节）和 run summary（运行聚合）的分工，以及为什么只靠 tracing 不够（聚合要预先算）。
