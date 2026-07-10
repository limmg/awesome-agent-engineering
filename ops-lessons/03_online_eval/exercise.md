# Lesson 03 练习

> 改 `code.py` 里的代码，运行 `python code.py` 观察变化。本课零外部依赖。

---

## 练习 1：感受采样率的「成本 vs 覆盖」权衡

把 `SAMPLE_RATE` 从 `0.3` 调成 `0.05`、`0.5`、`1.0`，分别跑，对比三项统计：抽中数、入队数、运行覆盖的坏 case 比例。

```python
SAMPLE_RATE = 0.05   # 试 0.05 / 0.5 / 1.0
```

**思考**：
- 5% 时，那 4 个明显坏的 case（幻觉/没答上）能全抓到吗？——大概率漏。
- 100% 时全抓到了，但生产日均万次问答意味着每天 20000 次 judge 调用。
- 这就是为什么生产典型值是 5%~10%：**统计上够发现系统性下降，又不至于破产**。但点踩信号永远 100%——因为它免费且精准。

---

## 练习 2：换一个更严的阈值过滤策略

现在用 `min(faithfulness, relevancy) < threshold`（任一维度低就入队）。改成：
- 策略 A：`avg < threshold`（平均分）
- 策略 B：`faithfulness < threshold`（只盯幻觉）

分别跑，对比入队的 case 有什么不同。

**思考**：
- `avg` 会被一个高分拉平——faithfulness=0.2 但 relevancy=0.95，avg=0.575 不入队，但这个答案明明在撒谎！这就是为什么用 `min` 更保守。
- 策略 B 适合「幻觉是最致命问题」的场景（医疗/法律知识库）。
- **阈值策略是产品决策**：你更怕「漏掉坏答案」还是「队列塞满假阳性」？知识库场景通常宁可多看（用 min）。

---

## 练习 3：给 review_queue 加「去重 / 聚合」

现在同一个坏问题可能被抽样多次、入队多次。给 `enqueue_review` 加逻辑：如果队列里已有**相同问题**的样本且时间在 1 小时内，就累加 `count` 字段而不是新增一行。

```python
# 伪代码
existing = find_recent_same_question(queue_path, sample["question"], within_hours=1)
if existing:
    existing["count"] += 1   # 高频坏 case 自动浮上来
else:
    append_new(queue_path, sample)
```

**思考**：这是坏答案队列从「流水账」变成「可排序待办」的关键——**高频出现的坏 case = 系统性问题，优先级最高**。运营看 `count` 排序，比逐条翻队列高效得多。落地版 `online_eval.py` 可以把这个做成一个简单的内存聚合。

---

## 练习 4（进阶）：接真实 ragas judge

本课的 `mock_judge` 是规则模拟。落地版 `kb_qa/online_eval.py` 接的是真实 ragas。如果你有 `ZHIPUAI_API_KEY`，体验真实 judge：

```bash
cd portfolio-projects/knowledge-base-qa
python -c "
import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
from kb_qa.online_eval import evaluate_sample
scores = asyncio.run(evaluate_sample(
    question='试用期多久',
    answer='试用期 3 个月，转正工资 100%。',
    contexts=['试用期 3 个月，转正后基本工资 100%'],
))
print('真实 ragas 分数：', scores)
"
```

对比 mock 分数和真实 LLM judge 分数的差异。

**思考**：真实 judge 比规则 mock 慢得多（每次 2 次 LLM 调用，几秒级），这正是为什么**必须异步、必须抽样**——同步全量跑会把服务拖垮。这也是 L01/L02 trace 里记录的 `usage`/`cost` 派上用场：你可以算出「线上评估每天额外花多少钱」，用数据决定采样率。

---

## ✅ 完成本课后，你应该能回答

1. 离线评估（golden set）和线上评估分别解决什么问题？为什么有了离线还要线上？
2. 线上没有 ground_truth，ragas 四指标里哪些还能跑？为什么恰好是这两个？
3. 为什么线上评估必须抽样？采样率 5% 在日均万次问答下成本是多少？
4. 为什么点踩样本要 100% 入队、跳过抽样？
5. review_queue.jsonl 为什么用 jsonl 而非 json 数组？
6. 阈值过滤为什么用 `min` 而不是 `avg`？
7. 线上评估为什么必须异步、不能阻塞用户响应？（落地）service.py 在哪里触发它？
8. （落地）`POST /api/feedback` 接口收到的点踩样本，走的是哪条入队路径？
