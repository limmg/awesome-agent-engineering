# Lesson 02 — 全链路追踪：接入 Langfuse

> 本课目标：**把 L01 的「日志能按 trace_id grep」升级成「面板上一眼看到每次问答每一步的耗时/输入输出/token/成本」**——这是 LLM 应用运维的行业标配。
>
> 学完你能回答面试官那句：**「昨天你的线上问答平均一次花多少钱？最慢的是哪一步？」**——不用翻日志翻到眼瞎，面板上就有。

---

## 1. 为什么 LLM 应用需要专门的 tracing？

L01 的结构化日志解决了「能查」，但还有三个痛点日志搞不定：

| 痛点 | 日志的局限 | tracing 解决方式 |
|---|---|---|
| 🚫 **链路是树不是线** | 日志是扁平行，看不出「rerank 是检索的子步骤」 | trace 是**树形**：一次问答下挂着检索/rerank/生成的嵌套 span |
| 🚫 **非确定性难复盘** | 同样的问题两次答案可能不同，光看日志还原不出当时的输入输出 | span 完整记录每次调用的 input/output/model/参数 |
| 🚫 **成本看不见** | 日志里只有估算 token，算不出「今天烧了多少钱」 | generation span 带 usage + 单价，面板自动汇总成本 |

> 🎯 **核心认知**：传统 Web 服务（CRUD）链路短、确定性强，日志够用；**LLM 应用链路长（改写→检索→rerank→生成）、非确定性、按 token 计费**——这三点让 tracing 从「锦上添花」变成「刚需」。

```
传统服务：  请求 → 查库 → 返回          （2 步，日志够看）
LLM 服务：  请求 → 改写 → 检索 → rerank → 生成 → 后处理   （5+ 步，每步都可能出问题）
                          │         │          │
                       每步都要看  哪步最慢  烧了多少 token
```

---

## 2. Langfuse 是什么？

**Langfuse** = 开源的 LLM 应用可观测平台。三个关键定位：

| 维度 | Langfuse 的选择 | 为什么 |
|---|---|---|
| **开源** | MIT 协议，可自己 Docker 部署 | 数据不出公司（企业知识库场景的硬需求） |
| **框架无关** | 不绑 LangChain，纯 SDK 埋点 | kb-qa 用的 LangChain、research-assistant 用的原生调用都能接 |
| **国内可用** | 自部署无墙；云版也还行 | 对比 LangSmith（OpenAI 系）国内访问不稳 |

**vs LangSmith 的取舍：**
- LangSmith：LangChain 官方，集成最丝滑，但闭源、数据存美国、国内访问受限
- Langfuse：开源可自部署、框架无关、国内可用 → **本课程选它**

> 💡 选型不是「谁更好」，是「哪个符合约束」。我们的硬约束是「数据可控 + 国内可用」，Langfuse 命中。

---

## 3. trace / span / generation：核心概念模型

Langfuse（和几乎所有 tracing 系统）的数据模型是这个三层结构：

```
trace（一次完整请求）
  │  例：用户问 "试用期多久"
  │
  ├── span（一个步骤/操作）
  │     例：condense 改写问题
  │     记录：name / input / output / start_time / end_time
  │
  ├── span：retrieve 检索
  │     └── span：rerank 重排          ← span 可以嵌套（树形！）
  │
  └── generation（一次 LLM 调用 —— 特殊的 span）
        额外记录：model / usage(input/output tokens) / cost
        例：glm-4 生成答案，in=820 tokens, out=210 tokens
```

| 概念 | 是什么 | 关键字段 | 类比 |
|---|---|---|---|
| **trace** | 一次用户请求的完整链路 | id, name, input, output, user_id | 一次外卖订单 |
| **span** | 链路里的一个步骤 | name, input, output, start, end, metadata | 订单里的「备餐」「配送」 |
| **generation** | 特殊 span = 一次 LLM 调用 | model, usage, cost | 配送里的「骑手接单」（要单独算钱） |

> 🎯 **generation 为什么单独拎出来？** 因为它是**唯一按用量计费**的步骤。一个 trace 里可能有多个 generation（改写用 flash、生成用 glm-4），每个都要单独记 token 和成本。面板的「成本汇总」全靠 generation span 的 usage 字段。

---

## 4. 成本核算：把 token 变成钱

这是 LLM tracing 独有的、最值钱的能力。公式：

```
单次 generation 成本 = input_tokens × 输入单价 + output_tokens × 输出单价
```

智谱 GLM 的单价（2026 年公开价，写进配置可改）：

| 模型 | 输入（元/百万token） | 输出（元/百万token） |
|---|---|---|
| glm-4 | 50 | 50 |
| glm-4-flash | 免费 | 免费 |

一次问答成本举例：
```
改写（flash）：in=200 out=30  → 免费（flash）
生成（glm-4）：in=820 out=210 → (820+210)×50/1e6 ≈ 0.0515 元
```

面板会自动把所有 generation 加总，回答「今天烧了多少」。

> 💡 这正是 L12「成本/质量权衡」的数据基础——trace 里的 usage 是真实的，比 L01 的估算准。L02 先把数据采上来。

---

## 5. 接入方式：低级 API（手动埋点）

Langfuse 提供三种埋点方式，本课用手动低级 API（最显式、最教学）：

```python
from langfuse import get_client

lf = get_client()  # 从环境变量读 host/public_key/secret_key；没配则自动 no-op

# ① 开一个 trace（一次问答）
with lf.start_as_current_observation(as_type="span", name="kb_qa.ask") as trace:
    trace.update(input=question, metadata={"thread_id": ..., "mode": ...})

    # ② 子 span：检索（嵌套在 trace 下 → 自动成树）
    with lf.start_as_current_observation(as_type="span", name="retrieve") as span:
        docs = retrieve(query)
        span.update(input=query, output=[d.page_content for d in docs],
                    metadata={"hits": len(docs)})

    # ③ generation：生成（带 model + usage）
    with lf.start_as_current_observation(
        as_type="generation", name="answer", model="glm-4"
    ) as gen:
        answer, usage = generate(...)
        gen.update(input=..., output=answer,
                   usage={"input": usage.in, "output": usage.out, "unit": "TOKENS"})

lf.flush()  # 异步上报，退出前 flush 确保不丢
```

> 💡 **上下文管理器（`with`）自动建立父子关系**：内层的 `with` 会成为外层当前的子节点，不用手动传 parent_id。这就是 trace 能长成「树」的原理。

---

## 6. 无 Langfuse 服务怎么办？—— 降级路径

本课的硬约束（任务书要求）：**没装 Langfuse 或没配服务时，代码必须能跑、给出等价的可观测**。我们的设计：

```
                 tracing.py 初始化时探测
                         │
            ┌────────────┴────────────┐
       有 Langfuse SDK              无 SDK
            │                          │
   LANGFUSE_HOST 配了？           用 ConsoleTracer
      │         │                  （把 trace 树打印到控制台）
     配了      没配                    │
      │         │                  效果：不依赖任何外部服务
   真实上报   ConsoleTracer          也能看到完整的树形链路
              （本地调试常用）
```

三种状态：
- ✅ **完整模式**：装了 langfuse + 配了服务 → 真实上报到面板
- 🔶 **控制台降级**：装了 langfuse 但没配服务，或根本没装 → 打印 trace 树到 stdout
- 这样 L01–L12 的代码在任何环境都能跑，真实面板验证留给有 Docker 的同学

> ⚠️ **诚实标注**：执行环境**未实测真实 Langfuse 面板上报**（无 Docker 起 Langfuse 服务）。代码逻辑严格参照官方 SDK v3 文档；本机验证走「控制台降级」路径——会打印一棵等价的 trace 树。README 给出有 Docker 环境的完整自部署命令。

---

## 7. 本课代码会做什么

### `code.py`（教学，零外部依赖）
- 实现 `ConsoleTracer`：一个不依赖 Langfuse 的 trace/span/generation 树形记录器
- 用它跑一次「检索→rerank→生成」，打印出一棵带耗时/usage/成本的 trace 树
- 展示「成本自动汇总」：把两次 generation（flash 改写 + glm-4 生成）的钱加起来

### 落地到 kb-qa
- 新增 `src/kb_qa/tracing.py`：探测 Langfuse，没装/没配则降级为 ConsoleTracer；统一的 `trace_span` / `trace_generation` 上下文管理器接口
- `config.py`：加 `langfuse_host` / `langfuse_public_key` / `langfuse_secret_key` / `langfuse_enabled`（默认空=关）
- `service.py`：在 L01 的日志埋点基础上，叠加 tracing 埋点（一个 trace 包住整次问答，检索/改写/生成各成 span/generation）
- `docker-compose.langfuse.yml`：一键起 Langfuse（自部署）
- `.env.example`：补 Langfuse 配置说明

---

## 8. 跑起来

### 教学代码（零依赖，验证 trace 树概念）

```bash
cd ops-lessons/02_langfuse_tracing
python code.py
```

预期：打印一棵 trace 树，能看到 retrieve→rerank→generate 的嵌套、每步耗时、glm-4 的 token 成本，底部汇总「本次问答总成本」。

### 落地验证（kb-qa，控制台降级模式）

```bash
cd portfolio-projects/knowledge-base-qa
# 不配任何 Langfuse 环境变量 → 自动降级打印 trace 树
python -m pytest tests/test_tracing.py -q
# 看一次问答的 trace 树（需 ZHIPUAI_API_KEY；无则看降级输出）
python -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
import asyncio
from kb_qa.tracing import flush
from kb_qa.service import stream_ask
async def go():
    async for ev in stream_ask('云帆科技试用期多久？', 'demo'):
        pass
    flush()
asyncio.run(go())
" 2>&1 | grep -A20 "trace"
```

预期（降级模式）：stdout 打印一棵 trace 树，含 ask / retrieve / generate 节点，generate 带 token 与成本。

### 真实 Langfuse 面板（需要 Docker，本机未实测）

```bash
cd portfolio-projects/knowledge-base-qa
docker compose -f docker-compose.langfuse.yml up -d   # 起 Langfuse
# 在 .env 配 LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY（面板里建项目获得）
# 然后跑问答，打开 http://localhost:3000 看 trace
```

---

## 🎯 面试话术

> 「我接了 Langfuse 做全链路 tracing，每次问答是一个 trace，检索、rerank、生成各成 span，LLM 调用是带 usage 的 generation。面板上能直接回答『昨天平均一次问答花多少钱、最慢的是检索还是生成』。选 Langfuse 是因为开源可自部署、数据不出公司、国内可用——LangSmith 数据存美国不符合我们的合规要求。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/kb_qa/tracing.py` | **新增**：`init_tracing()`、`current_trace()`、`trace_span()`、`trace_generation()`、`flush()`；装了 langfuse 走真实 SDK，否则降级 ConsoleTracer | `python -c "from kb_qa.tracing import init_tracing; init_tracing(); print('ok')"` |
| `src/kb_qa/config.py` | 加 `langfuse_enabled` / `langfuse_host` / `langfuse_public_key` / `langfuse_secret_key` | `.env` 配了即启用 |
| `src/kb_qa/service.py` | `stream_ask` 开 trace，condense/retrieve/generate 包成 span/generation | 跑问答看 trace 树输出 |
| `docker-compose.langfuse.yml` | **新增**：一键自部署 Langfuse（端口 3000） | `docker compose -f docker-compose.langfuse.yml up -d` |
| `.env.example` | 补 Langfuse 配置段 | — |
| `tests/test_tracing.py` | **新增**：测降级 trace 树结构、span 嵌套、cost 汇总（全 mock） | `pytest tests/test_tracing.py -q` 全绿 |

下一课 [Lesson 03 — 线上评估闭环](../03_online_eval/) 把 trace 里的问答记录接上 ragas 自动打分。
