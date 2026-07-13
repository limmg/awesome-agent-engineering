# L09 练习

## 练习 1：智能路由——什么子问题值得 browse（方法练习）

当前 `enable_browser=true` 时对所有子问题都 browse（`max_pages=2` 控成本）。加智能路由：

1. 在 researcher 里加判断：子问题含「版本/release/日期/changelog/对比」关键词 → 开 browse；纯概念解释 → 跳过。
2. 跑同一主题，对比「全 browse」vs「智能路由」的浏览页数和 finding 质量。
3. 量化省了多少 browse 调用（成本）。

**验收**：智能路由显著减少 browse 次数，且关键子问题（需详情页的）仍 browse。这把 L09 的「全开」优化为「按需开」。

---

## 练习 2：证据去重与质量评分（设计实验类）

browse 多页可能拿到重复或低质证据。设计去重+评分：

1. **假设**：多页证据有重复（同一 release 在多个页出现）+ 低质（404 页/空内容）。
2. **实验**：
   - 给 Evidence 加 `quality_score`（基于内容长度/是否含版本号模式/是否空）。
   - browse 后去重（按 URL+内容哈希）+ 按 quality 排序 + 取 top-k。
   - 对比去重前后进 prompt 的证据数和 token。
3. **预期**：去重+评分后证据数↓、质量↑、token↓。

**验收**：去重前后对照表，token 显著降且关键证据保留。这是 L10 证据链的前置工程。

---

## 练习 3：降级链的覆盖测试（理解类）

当前降级有三层（单页失败/整批失败/工具不可用）。回答：

1. 写一个测试：mock `extract_from_page` 对某些 URL 抛异常，验证 `browse_for_evidence` 跳过失败的、返回成功的。
2. 写一个测试：mock 整个 `browse_for_evidence` 抛异常，验证 researcher 的 try/except 把 browser_evidence 置空、finding 仍含 search 摘要。
3. 这两层降级哪个更关键？为什么？

**验收**：两个测试都过。能说出「整批失败降级更关键——它保证研究流程不断；单页失败是细粒度优化」。这对应 ops 课「优雅降级」的分层思想。

---

## 练习 4：思考题——async 落地的 Windows 坑（取舍类）

任务书点名的 ProactorEventLoop 坑。回答：

1. research-assistant 是 LangGraph async 图，browse 是 async——它们共享一个事件循环。Windows 上若有人误设 SelectorEventLoop 会怎样？
2. 怎么在代码里防这个坑？（提示：启动时检查 `asyncio.get_event_loop_policy()` 类型，非 Proactor 时警告）
3. 为什么 sync API 教学版（L01）没这个问题，async 落地版才有？

**验收**：能说出「async 子进程通信在 SelectorEventLoop 上挂死，sync 不涉及子进程通信所以没事」。并给出启动检查的写法。这是 Windows 生产环境的真实坑，README 已写明。
