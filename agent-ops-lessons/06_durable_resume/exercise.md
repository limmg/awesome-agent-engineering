# L06 练习

> 改 `code.py` 或 research-assistant 的代码，运行观察变化。本课零外部依赖。

---

## 练习 1：实测「重做量=最后一个未完成节点」（理解类）

跑 `code.py` 的 Part 1，看 call_counts。

1. 为什么 `research_team` 的 call_count 恢复后还是 1（没重做）？
2. 为什么 `writer` 的 call_count 是 2（重跑了）？
3. 如果 interrupt 放在 `research_team` 而不是 `writer`，恢复后哪个节点重做？（提示：research_team 会重跑，因为它是中断点。前面的节点（无）不重做。）

**验收**：能用「中断前完成的 vs 中断所在的」解释 call_count 的差异，说清「重做量有界」的精确含义（不是零重做，而是从一个节点起算）。

---

## 练习 2：设计实验——重做成本对比表（设计实验类）

量化 before（裸奔）vs after（checkpoint 续跑）的重做成本。

1. **假设**：裸奔的重做成本 ≈ 全程 token × 2；checkpoint 续跑的重做成本 ≈ 全程 token × (1 + 1/N)，N 是总节点数。
2. **实验设计**：
   - 在 `code.py` 给每个节点加 token 计量（research_team=1000, writer=500, reviewer=300）。
   - 崩在 writer 后：裸奔重做 research_team+writer+reviewer = 1800 token；checkpoint 续跑只重做 writer = 500 token。
   - 打印两种模式的重做成本对比表。
3. **预期**：checkpoint 续跑的重做成本是裸奔的 ~28%（500/1800），节点越多优势越大。
4. **思考**：如果崩在 reviewer（最后一个节点），两种模式差距多大？（提示：裸奔重做全部，checkpoint 续跑只重做 reviewer——差距最大，因为前面所有节点都白做了。）

**验收**：产出重做成本对比表（token 数），说清 checkpoint 续跑的优势随「崩溃点靠后」而增大。

---

## 练习 3：证明幂等键是断点续跑不重放副作用的地基（设计实验类）

writer 重跑时会再调 publish。没有幂等键 = 重复发布；有幂等键 = no-op。

1. **假设**：L06 的 checkpoint 续跑会让 writer 重跑一次，如果 writer 内调 publish，没有幂等键就会重复发布。
2. **实验设计**：
   - 用 L04 的 `publish_report`：先正常发布一次（"内容"），模拟 writer 崩溃。
   - 「恢复」：再调一次 `publish_report("同thread", "内容")`（writer 重跑）。
   - 看发布历史记录数。
3. **预期**：有幂等键 → 历史记录 1 条（第二次 no-op）；无幂等键 → 历史记录 2 条（重复发布）。
4. **思考**：这证明了什么依赖关系？（提示：L04 → L06。幂等键必须先做，否则断点续跑会重放副作用，把「重做量有界」的好处抵消掉——成本是有界了，但副作用事故还在。）

**验收**：能展示「有幂等 vs 无幂等」的发布历史差异，说清 L04→L06 的依赖（幂等是恢复安全的地基）。

---

## 练习 4：思考题——Temporal 工作流引擎什么时候才需要（取舍类）

方案对比提到 Temporal/事件溯源是分布式正统，但讲概念不实现。

1. **思考**：Temporal 是什么？（提示：一个分布式工作流引擎，每步活动（activity）的输入输出都持久化，失败从活动边界重试，支持长周期（几天几个月）的工作流。）
2. **思考**：research-assistant 需要 Temporal 吗？（提示：不需要——它是单进程、秒到分钟级的研究任务。langgraph 的 checkpointer + jobs 表就够。）
3. **结论**：用一句话说清「什么规模才需要 Temporal」（跨服务、跨团队、长周期、需要人工审批嵌在工作流里的复杂编排），以及为什么单体 Agent 用 checkpointer 就够。

**验收**：能说清 Temporal 的适用场景（分布式长周期工作流编排），以及为什么单体 Agent 用 langgraph checkpointer + jobs 表就够。
