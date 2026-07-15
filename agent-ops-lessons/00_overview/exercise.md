# L00 练习

> 改 `code.py` / `eval_agent/chaos.py` 里的代码，运行 `python code.py` 观察变化。本课零外部依赖，全离线。

---

## 练习 1：读懂基线档案，给五类失控填「现状爆炸半径」（理解类）

打开 `baseline_chaos.json`，对五种失控形态（循环 / 成本 / 故障扩散 / 危险副作用 / 中途崩溃）各写一句话：现状的爆炸半径是「无界」到什么程度？参考格式：

| 失控形态 | 现状爆炸半径（无界到什么程度） | 哪课治理 |
|---|---|---|
| 死循环 | 局部限位兜住但 3×2×N 叠乘后仍可达 recursion_limit=25 才崩 | L01 |
| ... | ... | ... |

**验收**：五行填满，每行的「无界」描述能对应 `baseline_chaos.json` 里的具体数字（步数 / token / 发布次数）。

---

## 练习 2：设计实验——叠加故障，看爆炸半径怎么涨（设计实验类）

现状的六类故障是**单类注入**的。真实生产里故障常常**叠加**（例如：搜索又慢又坏，还赶上预算炸弹）。

1. **假设**：两类故障叠加（如 `slow` + `bomb`），爆炸半径比单类更大（步数和 token 都涨）。
2. **实验设计**：
   - 在 `chaos.py` 里造一个「组合注入器」：让 `web_search` 既挂起又吐超长文本（先 hang 再返回 bomb）。
   - 在 `code.py` 的 `run_baseline_suite()` 加一个 `"slow_bomb"` 场景，用这个组合注入器。
   - 跑 `python code.py`，对比 `slow` / `bomb` / `slow_bomb` 三行的步数和 token。
3. **预期**：`slow_bomb` 的 token ≈ `bomb`（超长文本照吃不误），但耗时更长（先等超时）。这说明**叠加故障的成本是叠加的，但现状没有任何一层能挡住组合攻击**。
4. **思考**：为什么单类治理（每课修一类）仍然有效？因为组合故障的每一类都被对应的机制拦住了——L01 拦步数、L02 拦 token、L03 拦降级，叠加故障 = 每个机制各挡一道。这就是「分层治理」为什么比「单一银弹」更鲁棒。

**验收**：`slow_bomb` 场景跑通，输出表多一行；能看到 token 不低于 `bomb` 单类；`baseline_chaos.json` 的 `scenarios` 里多一条记录。

<details><summary>提示：组合注入器怎么写</summary>

```python
def slow_bomb_factory(real_search, hang=20.0, bomb_chars=40000):
    async def slow_bomb(query, max_results=None):
        await asyncio.sleep(hang)  # 先挂起（会被 timeout 打断，但 bomb 那行单独测时不挂）
        padding = "超长内容..." * (bomb_chars // 4)
        return f"[{query}] {padding[:bomb_chars]}"
    return slow_bomb
```
注意：因为 `search_timeout` 会打断 hang，测组合时要把 `SEARCH_TIMEOUT` 临时调大（或让 hang < timeout），否则你测到的是「timeout 打断了 bomb」。这个边界本身就是 L03 要讲的事。
</details>

---

## 练习 3：证明「降级不诚实」是结构性的（设计实验类）

现状 `web_search` 超时返回 `f"搜索 '{query}' 超时（{timeout}s）..."`，这个字符串会混进 findings 被 LLM 当成材料。

1. **假设**：只要工具失败返回的是「字符串」而非「结构化降级标记」，下游就无法区分「真实内容」和「失败提示」。
2. **实验设计**：
   - 在 `code.py` 的 `_run_trajectory` 里，给 researcher 的 finding 加一行：`if "超时" in f or "失败" in f: print(f"⚠️ 污染检测：'{f[:30]}...' 被当成材料传给了 summarize")`。
   - 跑 `python code.py`，观察 `slow` 和 `flaky` 场景有没有打印这行。
3. **预期**：两个场景都打印了污染检测——证明现状的 findings 列表里**混着失败字符串**，summarize 会把它当事实总结进报告。
4. **思考**：L03 的「诚实降级」要怎么解决这个问题？（提示：工具返回结构化结果 `{ok/degraded/failed, 原因, 内容}`，degraded 的内容在 prompt 里显式标注，报告里声明「N 个子题检索失败」。）

**验收**：污染检测打印了至少 2 次（slow + flaky）；能说清楚「字符串降级」为什么比「结构化降级」危险。

---

## 练习 4：思考题——为什么 kb-qa 不需要这套机制（取舍类）

本课说「kb-qa 是线性链，用不上护轨迹的机制」。但 kb-qa 也有 `web_search`（不对，kb-qa 用的是向量检索），也可能超时。

1. **思考**：kb-qa 的检索超时会怎样？（提示：看 ops-lessons 怎么处理 kb-qa 的降级——是请求级兜底，客户端重试。）
2. **思考**：为什么 kb-qa 不需要「步数预算」「断点续跑」？（提示：它不循环、不长时间运行、没有副作用。一次请求秒回，崩了客户端重发即可。）
3. **结论**：用一句话说清「护请求」和「护轨迹」的对象差异，以及为什么这个差异决定了机制的有无。

**验收**：能用「对象不同（请求 vs 轨迹）」一句话解释，并指出 research-assistant 的哪个特征（循环）是 kb-qa 没有的、所以需要本课机制。
