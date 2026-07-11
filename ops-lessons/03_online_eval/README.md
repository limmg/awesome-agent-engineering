# Lesson 03 — 线上评估闭环：抽样 + 自动打分 + 坏答案队列

> 本课目标：**把离线的 ragas 评估（`eval/run_eval.py` 的一次性跑分）升级成线上持续闭环——对真实问答按比例抽样、自动跑指标、低分样本自动进「待优化队列」，把评估从「上线前跑一次」变成「上线后天天跑」**。
>
> 学完你能回答面试官那句：**「你的系统上线后，怎么持续发现质量下降？总不能每次都靠用户投诉吧？」**

---

## 1. 离线评估 vs 线上评估：为什么必须补上线上这一环？

kb-qa 已有一套离线评估（rag-lessons L08 的产物，固化在 `eval/run_eval.py`）：拿 20 道人工标注的 golden set，跑四指标，产出 `REPORT.md`。它解决的是「上线前，这个版本行不行」。

但离线评估有三个天生短板：

| 离线评估的短板 | 线上后果 |
|---|---|
| 🚫 **golden set 会过时** | 上线后用户问的真实问题，跟标注的 20 题分布不一样（口语化、错别字、追问） |
| 🚫 **只跑一次** | 文档更新了、模型升级了，没人重跑，质量悄悄下降你不知道 |
| 🚫 **发现不了新坏 case** | 真实流量里的新失败模式（某个新文档召回很差），离线集覆盖不到 |

> 🎯 **核心认知**：离线评估是「出厂质检」，线上评估是「售后监控」。质检合格的货，不代表用着不坏——你得持续盯着真实使用。这正是 L01/L02 采的数据派上用场的地方。

```
离线评估（已有）：  golden set ──跑一次──▶ REPORT.md      （上线前）
                              │
线上评估（本课）：  真实问答 ──抽样──▶ 自动跑 ragas ──▶ 低分进队列  （上线后持续）
                                    ▲
                                    └ 点踩的样本必入队（用户反馈信号）
```

---

## 2. 线上评估的核心难题：没有标准答案怎么办？

离线评估的 golden set 每题都有 `ground_truth`（人工标的标准答案）。线上没有——用户问完，你手上只有「问题 + 召回材料 + 生成的答案」，没人给你标正确答案。

所以**线上只能跑不需要 ground_truth 的指标**。ragas 四指标按是否需要参考答案分两类：

| 指标 | 评估啥 | 需要 ground_truth 吗 | 线上能跑？ |
|---|---|---|---|
| **faithfulness**（忠实度） | 答案有没有基于材料撒谎 | ❌ 只看 召回材料+答案 | ✅ **能** |
| **answer_relevancy**（答案相关性） | 答案切题吗 | ❌ 只看 问题+答案 | ✅ **能** |
| context_precision | 召回排序质量 | ✅ 需要标准答案 | ❌ 线上没有 |
| context_recall | 该召回的召回了吗 | ✅ 需要标准答案 | ❌ 线上没有 |

> 💡 **关键洞察**：线上能跑的两个指标恰好覆盖「生成层」——faithfulness 抓幻觉、answer_relevancy 抓跑题。而生成层是 LLM 应用最容易出问题、最难人工排查的地方。**线上评估不是「跑不了全部指标就放弃」，而是「能跑哪些就先跑哪些，先盯住最易出问题的生成层」**。

```
一次问答的四指标可行性：
   问题 ──▶ 检索 ──▶ 召回材料 ──▶ 生成 ──▶ 答案
    │                     │                  │
    │                     │                  ├─ faithfulness  ✅（材料 vs 答案）
    │                     │                  └─ answer_relevancy ✅（问题 vs 答案）
    │                     └─ context_precision ❌（要标准答案）
    └─ context_recall ❌（要标准答案）

→ 线上聚焦 ✅ 的两个：faithfulness + answer_relevancy
```

---

## 3. 为什么必须抽样？（成本约束）

理想是「每条真实问答都跑评估」。但现实跑不起：

```
每跑一次线上评估的成本 = 一次 judge LLM 调用（faithfulness + relevancy 各一轮）
                       ≈ glm-4 调用 2 次
```

如果日均 10000 次问答，全评估 = 每天 20000 次 extra LLM 调用——比正常服务还贵。所以**按比例抽样**：

| 采样率 | 适用场景 | 成本（日均1万问答） |
|---|---|---|
| 100% | 内测/低流量（<100/天） | 可接受 |
| 5%~10% | 生产常规监控 | 每天 500~1000 次评估 |
| 1% | 超高流量 + 只看趋势 | 每天 100 次，够画趋势 |

> 🎯 **采样率的本质是「成本 vs 覆盖率」的权衡**：太低抓不到坏 case，太高烧钱。生产典型值 5%——统计上足够发现系统性质量下降。

**例外：用户点踩的样本永远 100% 入队**。因为点踩是强信号——用户已经明确告诉你「这个答案不好」，这种样本比随机抽样有价值得多，不该被采样率漏掉。

---

## 4. 闭环：从坏答案到优化的飞轮

线上评估不是「打个分就完了」，它要驱动优化。完整的闭环：

```
   线上问答 ──抽样(5%)──┐
        │                │
        │           自动跑 ragas
        │           (faithfulness/relevancy)
        │                │
        │           分数 < 阈值？
        │           /        \
        │         是          否
        │          │           └─ 丢弃（这次没问题）
        │          ▼
   点踩的样本 ─▶ review_queue.jsonl  ◀── 100% 入队（强信号）
        │          │
        │      定期人工 review
        │      （看 bad case 找规律）
        │          │
        └──────▶ 针对性优化（改 prompt / 补文档 / 调检索）
                        │
                   下个版本重跑离线评估验证
                        │
                   └──▶ 质量提升，回到线上继续监控
```

关键产物：`eval/review_queue.jsonl`——一个**坏答案待办列表**，每行一条 JSON：问题、答案、召回材料、分数、时间、来源（抽样/点踩）。运营/算法同学定期扫这个队列，挑高频坏 case 优化。

> 💡 这就是「评估驱动优化」的工业实践：**不是拍脑袋决定优化什么，而是让数据（低分样本）告诉你哪里最该改**。

---

## 5. 线上评估的两条数据来源

本课的线上评估消费两路数据，都来自前两课的可观测性地基：

| 来源 | 触发 | 入队条件 |
|---|---|---|
| **抽样**（L01/L02 的问答记录） | `service.py` 每次问答后，按 `eval_sample_rate` 概率触发异步评估 | 分数 < 阈值（如 faithfulness < 0.5） |
| **点踩反馈**（本课新增 `/api/feedback`） | 用户在前端点「👎」 | **无条件入队**（强信号不抽样） |

> 这正是 L01/L02 提前埋点的回报——trace_id / 召回材料 / 答案都已经采好了，线上评估只是「把这些数据接上 judge 跑分」，不用重新改造问答流程。

---

## 6. 非阻塞：评估不能拖慢用户响应

核心工程约束：**线上评估必须异步，绝不能让用户等评估跑完才收到答案**。

```
用户提问 ──▶ 流式返回答案（正常速度，用户感知）
                 │
                 └ 答案发完 done 后 ──▶ 后台异步：抽样？跑评估？入队？
                                      （用户完全无感）
```

实现方式：`service.py` 在 `done` 事件发出后，用 `asyncio.create_task` 派发一个后台评估任务，不阻塞当前响应。评估失败也不影响用户——它只是「没采到这条数据」，不是「服务挂了」。

---

## 7. 本课代码会做什么

### `code.py`（教学，可 mock 跑）
- 演示完整的「抽样 → 跑 judge → 阈值过滤 → 入队」逻辑
- 用 mock 的 judge（不调真实 LLM）跑通闭环，看清数据流
- 对比「抽样入队」vs「点踩必入队」两种路径

### 落地到 kb-qa
- 新增 `src/kb_qa/online_eval.py`：`should_sample(rate)` 采样判定、`evaluate_sample()` 复用现有 ragas 管线跑 faithfulness+relevancy、`enqueue_review()` 写 jsonl
- `config.py`：加 `eval_sample_rate` / `eval_score_threshold` / `eval_review_queue_path`
- `service.py`：问答 `done` 后异步触发抽样评估（不阻塞）
- `api/main.py` + `schemas.py`：新增 `POST /api/feedback` 接口（点赞/点踩）
- 前端 `index.html`：答案后加 👍/👎 按钮
- `tests/test_online_eval.py`：测采样、阈值过滤、入队格式、feedback（全 mock）

---

## 8. 跑起来

### 教学代码（零依赖，mock judge）

```bash
cd ops-lessons/03_online_eval
python code.py
```

预期：模拟 20 条问答，按 30% 采样跑 mock judge，低分样本进 `review_queue_demo.jsonl`，最后打印「入队 N 条 / 抽样 M 条」，并演示一条点踩样本必入队。

### 落地验证（kb-qa）

```bash
cd portfolio-projects/knowledge-base-qa
# 1) 单测（全 mock，不打真实 API）
python -m pytest tests/test_online_eval.py -q
# 2) 看采样入队（需 ZHIPUAI_API_KEY；跑几次真实问答后看队列）
#    ⚠️ 诚实标注：单测（步骤1）全 mock 已验证通过；下面这条「真实 judge 打分→入队」
#    的端到端路径本机未连真实智谱 API 实测，逻辑与 eval/run_eval.py 的离线管线同构。
python -c "
import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
from kb_qa.service import stream_ask
async def go():
    async for _ in stream_ask('试用期多久', 'demo'): pass
    await asyncio.sleep(2)  # 等异步评估跑完
asyncio.run(go())
import pathlib
p = pathlib.Path('eval/review_queue.jsonl')
print('队列存在' if p.exists() else '本条未被抽中（概率事件，多跑几次）')
"
# 3) feedback 接口
curl -X POST http://localhost:8001/api/feedback -H "Content-Type: application/json" \
  -d '{"thread_id":"demo","question":"试用期多久","answer":"...","rating":"down"}'
# 点踩样本必入 review_queue.jsonl
```

---

## 🎯 面试话术

> 「我把离线 ragas 评估延伸到了线上：真实问答按 5% 抽样，后台异步跑 faithfulness 和 answer_relevancy——这两个不需要 ground_truth，正好覆盖最容易出问题的生成层。低分样本自动进 review_queue，加上前端点踩 100% 入队，形成『抽样+反馈』双信号的持续监控。这样质量下降不用靠用户投诉，数据自己会报警。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/kb_qa/online_eval.py` | **新增**：`should_sample`、`evaluate_sample`（复用 ragas 跑 faithfulness+relevancy）、`enqueue_review`（写 jsonl） | `python -c "from kb_qa.online_eval import should_sample; print(should_sample(1.0))"` |
| `src/kb_qa/config.py` | 加 `eval_sample_rate`/`eval_score_threshold`/`eval_review_queue_path` | `.env` 配 `EVAL_SAMPLE_RATE=0.3` |
| `src/kb_qa/service.py` | `done` 后 `asyncio.create_task` 异步触发抽样评估（不阻塞响应） | 跑问答后 `eval/review_queue.jsonl` 可能出现样本 |
| `api/schemas.py` | 新增 `FeedbackRequest`（thread_id/question/answer/rating） | — |
| `api/main.py` | 新增 `POST /api/feedback`：点踩必入队 | `curl` 点踩后队列出现该条 |
| `static/index.html` | 答案后加 👍/👎 按钮，点踩调 feedback 接口 | 前端点 👎 后刷新看队列 |
| `tests/test_online_eval.py` | **新增**：采样判定、阈值过滤、入队格式、feedback（全 mock） | `pytest tests/test_online_eval.py -q` 全绿 |

下一课 [Lesson 04 — API 鉴权与限流](../04_auth_ratelimit/) 进入安全模块，给这些接口加防护。
