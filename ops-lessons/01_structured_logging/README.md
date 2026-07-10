# Lesson 01 — 结构化日志：从 print 到可查询的事件流

> 本课目标：**把知识库问答服务从「靠 print 瞎猜」推进到「每次请求有唯一 trace_id 贯穿全链路、日志是可被 grep/jq 查询的结构化 JSON」**。
>
> 学完你能回答面试官那句：**「你的服务上线后出问题了，你怎么排查？」**——这是「写过 demo」和「运维过线上服务」的分界线。

---

## 1. 为什么不能用 print？

写练习代码时 `print(result)` 没问题。但服务一上线，print 立刻变成灾难：

| print 的问题 | 生产里的后果 |
|---|---|
| 🚫 没有时间戳 | 「这条日志是 3 秒前还是 3 小时前？」答不上来 |
| 🚫 没有级别 | 一条「正常进度」和一条「数据库挂了」长一样，报警系统无从下手 |
| 🚫 多请求交错 | 10 个并发用户同时 print，日志糊成一锅粥，分不清哪行属于谁 |
| 🚫 不是机器可读 | 想统计「今天报了多少错」只能人眼数，没法 `jq` / 入 ELK |
| 🚫 没法关闭 | 上线后想关 debug 输出？得回去删代码 |

> 🎯 **核心认知**：生产日志不是「给人读的字」，而是「给机器消费的事件流」。人读只是它顺带能做的一件事。

---

## 2. 可观测性三支柱（Observability 3 Pillars）

这是整个 LLMOps 模块的总框架，先把名词钉死。一个生产系统要能被「观察」，靠三根柱子：

```
        ┌─────────────── 可观测性（Observability）───────────────┐
        │                                                        │
   ┌────┴─────┐           ┌──────────┐            ┌─────────────┐
   │  日志    │           │   指标   │            │    追踪     │
   │  Logs    │           │  Metrics │            │   Traces    │
   │          │           │          │            │             │
   │ 离散事件 │           │ 聚合数值 │            │ 请求级链路  │
   │ "出错了" │           │ QPS=120  │            │ 检索→rerank │
   │ 带上下文 │           │ P95=2.1s │            │   →生成     │
   └────┬─────┘           └────┬─────┘            └──────┬──────┘
        │                      │                         │
        └────────────── 都靠 trace_id 串起来 ─────────────┘
```

| 支柱 | 回答什么问题 | 本课 / 后续课 |
|---|---|---|
| **日志 Logs** | 「那次请求到底发生了什么？」离散事件 + 上下文 | **本课 L01** |
| **指标 Metrics** | 「系统现在整体健康吗？」聚合数字（QPS、延迟、错误率） | L11 压测会触及 |
| **追踪 Traces** | 「这一次请求，慢在哪一步？」请求级的步骤链路 | **L02 Langfuse** |

> 💡 三者不是替代关系，是互补。日志是地基（最便宜、最先要有的），追踪是 LLM 应用最该补的（链路长、成本敏感），指标是规模上来后的总结。本课先打地基。

---

## 3. 结构化日志 vs 文本日志

关键区别在「输出长什么样」：

**🚫 文本日志（人写句子，机器难解析）：**
```
2026-07-10 14:23:01 INFO 检索完成，召回 8 条，耗时 320ms
```
想 grep 出「耗时 > 300ms 的检索」？得写正则从句子里抽数字，脆且易错。

**✅ 结构化日志（一行一个 JSON 对象，字段化）：**
```json
{"ts":"2026-07-10T14:23:01Z","level":"INFO","event":"retrieve.done","trace_id":"a1b2","stage":"retrieve","hits":8,"duration_ms":320,"mode":"rerank"}
```
现在 `jq 'select(.duration_ms>300)'` 一行搞定，也能直接灌进 ELK / Loki / Datadog。

> 🎯 **一句话**：结构化日志 = 把「一句话」拆成「字段」，代价只是多一层格式化，收益是日志从此可查询、可统计、可报警。

---

## 4. trace_id：贯穿一次请求的灵魂

这是本课最要命的概念。看个反例：

```
14:23:01 [用户A] 检索中
14:23:01 [用户B] 检索中
14:23:02 检索完成 召回8条      ← 这是 A 还是 B 的？？
14:23:02 生成中
```

并发一上来，日志彻底无法归属。解法：**给每次请求发一个唯一 `trace_id`，它出现在这次请求打出的每一条日志里。**

```
14:23:01 trace_id=a1b2  event=retrieve.start  user=A
14:23:01 trace_id=c3d4  event=retrieve.start  user=B
14:23:02 trace_id=a1b2  event=retrieve.done   hits=8   ← 一定是 A 的！
14:23:02 trace_id=a1b2  event=generate.start
```

现在 `grep trace_id=a1b2` 就能还原 A 这次请求的完整链路：改写→检索→rerank→生成。这就是 L01 落地要解决的头等大事。

```
   一次问答的 trace_id 串联（kb-qa service.py）
   ────────────────────────────────────────────
   ask(req) ──生成 trace_id──┐
                             │
   ┌─ event: request.start   trace_id=a1b2  q="试用期多久"
   ├─ event: condense.done   trace_id=a1b2  duration=120ms
   ├─ event: retrieve.done   trace_id=a1b2  hits=8 mode=rerank duration=320ms
   ├─ event: rerank.done     trace_id=a1b2  kept=4 duration=210ms
   └─ event: generate.done   trace_id=a1b2  tokens≈210 duration=1500ms
```

> 💡 trace_id 还能透传给下游：L02 把它带进 Langfuse，L04 带进鉴权日志，一个 id 串起整个运维故事。

---

## 5. 日志级别（Level）

级别决定「这条事件多要紧」，也是报警系统能用的最基本信号：

| 级别 | 什么时候用 | 例子 |
|---|---|---|
| `DEBUG` | 开发排障细节，生产默认关 | 「BM25 分词结果: [...]」 |
| `INFO` | 正常业务流转的关键节点 | 「检索完成 召回8条」 |
| `WARNING` | 不正常但能继续，该盯 | 「rerank 失败，降级到 hybrid」 |
| `ERROR` | 出错了，本次请求可能失败 | 「智谱 API 429 限流」 |

> 🚫 新手最容易犯的错：把所有东西都打 INFO，最后 INFO 里全是噪音，真正出事的 ERROR 被淹没。**原则：INFO 只打「能还原业务流程的最少节点」，细节用 DEBUG。**

---

## 6. 敏感信息脱敏（别把密钥写进日志）

结构化日志方便查询，但也意味着**敏感信息更容易被泄露到日志聚合系统里**。生产红线：

| 字段 | 该不该打 | 怎么处理 |
|---|---|---|
| `ZHIPUAI_API_KEY` | 🚫 绝不 | 日志里只出现 `key=***...3f2a`（掩码） |
| 用户完整问题 | ⚠️ 按需 | 内部知识库通常可打全量；面向 C 端要考虑隐私，可只打前 N 字符 |
| 用户 PII（手机号/身份证） | 🚫 绝不 | 入库前脱敏 |
| 召回文档全文 | ⚠️ 太长 | 只打 `preview` 前 120 字符（service.py 已经这么做） |

本课的 logger 提供 `mask_secret()` 工具，演示如何把 `sk-xxx` 这种值在落日志前掩码。

---

## 7. 本课代码会做什么

`code.py` 用**纯标准库 `logging`**（不引 loguru/structlog 等重依赖）实现一个轻量结构化 logger，并演示：

1. **JSON formatter**：把每条日志序列化成一行 JSON（含 ts/level/event/trace_id/业务字段）。
2. **trace_id 上下文**：用 `contextvars` 在一次「模拟问答」里自动给所有日志带上同一个 trace_id（async 安全）。
3. **模拟一次检索→生成**：打出带 trace_id 的完整事件链，演示 `grep` 还原链路。
4. **脱敏工具**：演示 API key 掩码。

> 💡 为什么不用 structlog/loguru？教学要先把原理讲透——结构化日志本质就是「把 dict 序列化成 JSON」+「上下文注入」。懂了这个，换什么库都是换皮。生产想升级，改 formatter 一行即可。

---

## 8. 落地到 kb-qa

本课不止演示，还真正改进 `portfolio-projects/knowledge-base-qa`：

- 新增 `src/kb_qa/observability.py`：JSON 结构化 logger + trace_id 上下文 + 脱敏工具。
- `config.py` 加可配置项：`log_level`、`log_json`（开关 JSON / 纯文本，方便开发期看人类可读输出）。
- `service.py` 的 `stream_ask` 注入 trace_id，并在 condense / retrieve / generate 各节点打结构化事件（耗时、召回数、token 估算）。
- `api/main.py` 的 `/api/ask` 把 trace_id 回吐到响应头 `X-Trace-Id`，前端/排障可拿这个 id 去日志里捞。

详见本目录 **「## 落地清单」**。

---

## 9. 跑起来

### 教学代码（独立可跑，零外部依赖）

```bash
cd ops-lessons/01_structured_logging
python code.py
```

预期：控制台打印若干行 JSON，每行都带同一个 `trace_id`，最后一行用 `grep` 模拟「按 trace_id 还原链路」。

### 落地验证（kb-qa）

```bash
cd portfolio-projects/knowledge-base-qa
# 1) 单测（全 mock，不打真实 API）
python -m pytest tests/test_observability.py -q
# 2) 跑一次真实问答看日志（需 ZHIPUAI_API_KEY + 已入库）
python -c "
import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
from kb_qa.service import stream_ask
async def go():
    async for ev in stream_ask('云帆科技试用期多久？', 'demo-thread'):
        print(ev['event'], ev['data'][:60])
asyncio.run(go())
" 2>&1 | grep '"event"'
```

预期：日志里能看到 `request.start` → `retrieve.done` → `generate.done`，且这些行共享同一个 `trace_id`。用 `grep <那个trace_id>` 可还原整条链路。

---

## 🎯 面试话术

> 「我的服务每次请求会生成唯一 trace_id，用 contextvars 在异步链路里贯穿检索和生成。日志是结构化 JSON（字段化而非句子），线上排障我按 trace_id 一 grep 就能还原整条链路——哪步慢、召回几条、token 多少一目了然。这是接 Langfuse 全链路追踪、做线上评估的地基。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/kb_qa/observability.py` | **新增**：`JsonFormatter`、`get_logger`、`trace_context`（contextvars）、`new_trace_id`、`mask_secret`、`estimate_tokens` | `import kb_qa.observability as o; print(o.mask_secret('sk-abcdefgh'))` → `***cdefgh` |
| `src/kb_qa/config.py` | 加 `log_level: str="INFO"`、`log_json: bool=True` | 改 `.env` 设 `LOG_JSON=false` 后日志变人类可读文本 |
| `src/kb_qa/service.py` | `stream_ask` 注入 trace_id，condense/retrieve/generate 各打结构化事件 | 跑问答后 `grep trace_id` 能还原链路 |
| `api/main.py` | `/api/ask` 响应头回吐 `X-Trace-Id`；启动时初始化日志 | `curl -i` 看到 `X-Trace-Id` 头 |
| `tests/test_observability.py` | **新增**：测 trace_id 贯穿、脱敏、JSON 格式、配置开关 | `pytest tests/test_observability.py -q` 全绿 |

下一课 [Lesson 02 — 全链路追踪：接入 Langfuse](../02_langfuse_tracing/) 把这套 trace_id 升级成可视化面板。
