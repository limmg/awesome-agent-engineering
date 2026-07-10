# Lesson 02 练习

> 改 `code.py` 里的代码，运行 `python code.py` 观察变化。本课零外部依赖。

---

## 练习 1：观察「树形」——把 rerank 挪到 retrieve 外面

现在 `rerank` 是 `retrieve` 的子 span（嵌套）。把它改成 retrieve 的**兄弟**节点（移出 `with tracer.span("retrieve")` 块），再跑一次。

观察 trace 树从：
```
├─ SPAN retrieve
│  └─ SPAN rerank        ← 嵌套（rerank 是 retrieve 的子步骤）
```
变成：
```
├─ SPAN retrieve
├─ SPAN rerank           ← 平级（语义变了：rerank 不再属于 retrieve）
```

**思考**：span 的嵌套关系不是随便摆的，它表达**业务语义的包含关系**。rerank 到底是不是检索的一部分？这取决于你怎么看系统架构——但无论如何，trace 树应该如实反映你的设计意图。这也是 tracing 比扁平日志强的地方：它能表达「层级」。

---

## 练习 2：加一个失败的 generation，记录 error

真实场景：智谱 API 偶尔限流（429）。在 `Span` dataclass 加一个 `error: str | None = None` 字段，然后在 `fake_generate` 里模拟失败：

```python
import random
if random.random() < 0.3:  # 30% 概率失败
    gen.error = "RateLimitError: 429"
    gen.output = ""  # 没产出
    return "[生成失败，请重试]"
```

在 `render` 里给有 error 的 span 打个 ❌ 标记。

**思考**：失败也要有 trace！线上最常排查的就是「为什么这次问答挂了」——失败的 generation 带上 error 和当时的 input，能让你看清是哪步、什么输入触发的。这是 tracing 的「异常复盘」价值。

---

## 练习3：多轮问答的成本累积

`handle_ask` 现在只跑一轮。改成模拟「同一会话连问 3 次」（在同一个 trace 下连续 3 次 retrieve+generate），看 `total_cost()` 怎么变。

```python
with tracer.start_trace("kb_qa.session", session_id="abc") as t:
    for q in ["试用期多久？", "转正工资呢？", "病假怎么请？"]:
        # 每次 retrieve + generate
```

**思考**：一个 trace 可以代表「一次请求」也可以代表「一次会话」。Langfuse 面板支持按 session 聚合——连问 3 次总共烧了多少钱、平均延迟多少，这是评估「单用户成本」的基础。L12 会用这个数据做选型决策。

---

## 练习 4（进阶）：真实接一次 Langfuse

如果你有 Docker 环境，体验真实面板（本课执行环境没实测，但命令给你）：

```bash
# 1. 起 Langfuse（自部署）
docker compose -f portfolio-projects/knowledge-base-qa/docker-compose.langfuse.yml up -d
# 2. 打开 http://localhost:3000 建项目，拿到 public_key / secret_key
# 3. 装 SDK + 配环境变量
pip install langfuse -i https://pypi.tuna.tsinghua.edu.cn/simple
# 在 .env 加：
#   LANGFUSE_ENABLED=true
#   LANGFUSE_HOST=http://localhost:3000
#   LANGFUSE_PUBLIC_KEY=pk-...
#   LANGFUSE_SECRET_KEY=sk-...
# 4. 跑一次问答
python -c "import asyncio; from kb_qa.service import stream_ask; from kb_qa.tracing import flush; \
asyncio.run((lambda: [async for ev in stream_ask('试用期多久','t1'), flush()][1])())"
# 5. 回面板看 trace
```

**思考**：对比面板的可视化和 `code.py` 的 ASCII 树——内容一样，但面板能筛选、排序、按时间聚合、看成本趋势。这就是为什么生产要用平台而不是 print：**数据采上来之后，分析能力天差地别**。但采集的「埋点逻辑」你已经手写掌握了。

---

## ✅ 完成本课后，你应该能回答

1. 为什么 LLM 应用需要专门的 tracing，传统日志不够用？三个原因。
2. trace / span / generation 各是什么？generation 为什么单独拎出来？
3. 嵌套的 span 是怎么自动建立父子关系的？（提示：栈 / context）
4. 一次问答的成本怎么算？为什么 flash 改写 + glm-4 生成的组合能省钱？
5. Langfuse vs LangSmith，你的项目为什么选前者？
6. 没 Langfuse 服务时，kb-qa 的 tracing 怎么降级？为什么必须保证降级能跑？
7. （落地）kb-qa 的 `tracing.py` 暴露了哪几个上下文管理器？service.py 在哪几处用了它们？
