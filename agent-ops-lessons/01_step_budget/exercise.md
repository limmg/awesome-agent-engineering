# L01 练习

> 改 `code.py` 或 research-assistant 的代码，运行观察变化。本课零外部依赖。

---

## 练习 1：算最坏步数上界（理解类）

现状配置 `num_subtopics=3` / `max_rewrites=3` / `max_re_research=2`。手动算一次运行的最坏步数上界（所有回路都拉满）。

提示拓扑：`split(1) → researcher×3 → summarize(1) → [writer(1)→reviewer(1)]×max_rewrites → [research_team(含3 researcher+summarize)→writer→reviewer]×max_re_research`。

**验收**：算出一个数字，并判断它是否超过 `recursion_limit=25`。若超过，说明现状在最坏情况下会撞 recursion_limit 崩——这就是 L01 要解决的。

---

## 练习 2：设计实验——max_total_steps 设多少合适（设计实验类）

`max_total_steps` 是「紧松」判断的核心参数。

1. **假设**：设太小（如 5）会误杀正常任务（正常研究路径就要 7+ 步）；设太大（如 100）等于没设。
2. **实验设计**：
   - 在 `code.py` 里把循环诱导关掉（用 `good_search`），改成正常路径。
   - 设 `max_total_steps` 分别为 5 / 10 / 20 / 50，各跑一次，看哪些值会误触发诚实收尾。
   - 找到「正常路径不触发，但循环诱导能拦住」的最小区间。
3. **预期**：正常路径约 7–9 步，所以 `max_total_steps` 应 > 9（给余量）。循环诱导在局部限位下约 9–11 步，所以 `max_total_steps` 应 < 最坏崩崩溃步数。
4. **思考**：为什么默认值设 30 而不是 10？（提示：`enable_*` 开得越多，路径越长。开了 memory/code/browser 的完整 v2 路径比裸路径长。）

**验收**：给出一个 `max_total_steps` 推荐值，并说清依据（正常路径步数 × 安全系数）。

---

## 练习 3：让循环检测在「同节点连续重复」场景下触发（设计实验类）

`code.py` 里循环检测没触发，因为 research_team/writer/reviewer 交替出现，签名不连续重复。但有些循环是「同节点连续重复」（如 browser 反复点同一个按钮、researcher 反复查同一个 query）。

1. **假设**：动作签名检测对「同节点连续重复 N 次」的循环有效，对「跨节点交替」的循环无效。
2. **实验设计**：
   - 在 `code.py` 的 `run_review_loop` 里，模拟一个「reviewer 连续打回同一版报告」的场景——让 history 连续追加 `reviewer:rework` 3 次以上。
   - 开 `enable_loop_detect=True, loop_detect_window=3`，看是否触发。
3. **预期**：连续 3 个 `reviewer:rework` 签名相同 → `detect_loop` 返回 True → 诚实收尾。
4. **思考**：签名检测的局限是什么？（提示：它看的是「动作相同」，不是「语义相同」。如果 researcher 用不同 query 查但语义重复，签名检测抓不到。这就是为什么 frontier-L08 还需要 LLM judge 做语义级循环检测。）

**验收**：修改后的 `code.py` 跑出循环检测触发；能说清签名检测 vs 语义检测的覆盖差异。

---

## 练习 4：思考题——诚实收尾为什么不能在 writer 里做（取舍类）

现状 L01 的诚实收尾检查放在 **reviewer 节点开头**，而不是 writer。为什么？

1. **思考**：如果放在 writer 开头检查预算，writer 超预算时该返回什么？（提示：writer 是生成报告的节点，它不负责「决定要不要继续」。）
2. **思考**：reviewer 是条件边的决策点（pass/rework/re_research）——它能决定「不再打回，直接结束」。writer 没有这个能力（它后面一定接 reviewer）。
3. **结论**：诚实收尾本质是「**改路由决策**」（从 rework 改成 pass），必须放在能影响路由的节点。这和「为什么限位放在 reviewer 而不是 writer」是同一个道理。

**验收**：用「路由决策权」一句话解释为什么诚实收尾在 reviewer 不在 writer。
