# Lesson 01 练习

> 改 `code.py` 里的代码，运行 `python code.py` 观察变化。本课零外部依赖，纯标准库。

---

## 练习 1：用 jq 真正「按 trace_id 还原链路」

`code.py` 现在只把日志打到屏幕。把它重定向到文件，体验真实的排障：

```bash
python code.py > app.log 2>&1
# 挑一个 trace_id（比如演示 2 里的 04a69519），还原那一次请求的全部事件
grep '"trace_id": "04a69519"' app.log
# 进一步：只看耗时，按 duration_ms 排序找最慢的一步
grep '"event": "retrieve.done"' app.log
```

**进阶**：如果你装了 `jq`（`pip install jq` 只是绑定，建议装系统 jq），可以：
```bash
cat app.log | jq 'select(.trace_id=="04a69519") | {event, duration_ms}'
```

**思考**：如果日志是文本句子（「检索完成，耗时 51ms」），上面这些操作还能一行做到吗？这就是结构化的全部价值——**日志从「人读的字」变成「可查询的数据」**。

---

## 练习 2：加一个 WARNING 级别的降级日志

模拟真实场景：rerank 服务偶尔挂掉，系统降级到 hybrid 模式继续工作（kb-qa 的 `rerank.py` 真有这个降级逻辑）。在 `fake_generate` 前面加一段：

```python
import random
if random.random() < 0.3:  # 30% 概率模拟 rerank 失败
    log.warning("rerank 失败，降级到 hybrid 模式", extra={
        "event": "rerank.fallback",
        "reason": "upstream_timeout",
    })
```

跑几次，观察 WARNING 级别的日志长什么样。

**思考**：为什么降级是 `WARNING` 而不是 `ERROR`？因为——**本次请求还能正常完成（只是质量可能略降），ERROR 应该留给「请求失败了」。** 级别用错，报警系统会半夜叫醒你。

---

## 练习 3：证明 contextvars 在并发下不串扰

`code.py` 是顺序跑的，看不出 contextvars 的隔离价值。改成并发：

```python
import asyncio

async def concurrent_demo():
    await asyncio.gather(
        asyncio.to_thread(handle_ask, "问题A"),
        asyncio.to_thread(handle_ask, "问题B"),
        asyncio.to_thread(handle_ask, "问题C"),
    )

asyncio.run(concurrent_demo())
```

观察输出：三个请求的日志可能交错，但**每条日志的 trace_id 一定和它自己请求的开始/结束成对**——不会出现 A 的 retrieve.done 带了 B 的 trace_id。

**思考**：如果把 `_trace_id` 换成普通全局变量 `trace_id = ""`，并发下会发生什么？（答：后开始的请求会覆盖前一个的 id，日志彻底串台。）这就是为什么必须用 contextvars——它是 async/线程安全的「每请求一份」存储。

---

## 练习 4（进阶）：把 token 估算换成真实 tokenizer

`estimate_tokens` 是近似（中文按字、英文按 4 字符）。kb-qa 用的是智谱 GLM，可以装它的 tokenizer 精确计数：

```bash
pip install tiktoken -i https://pypi.tuna.tsinghua.edu.cn/simple
```

然后实现一个更准的版本，对比两者差多少。**思考**：日志里的 token 数是 L02 算成本的基础——估算越准，成本核算越可信。这就是为什么可观测性要尽早做（L01 的日志字段，是 L02 trace、L03 评估、L12 成本报告的共同数据源）。

---

## ✅ 完成本课后，你应该能回答

1. 生产服务为什么不能用 print？举出至少 3 个具体问题。
2. 可观测性三支柱是什么？它们各自回答什么问题？本课打的是哪根柱子？
3. 结构化日志（JSON）比文本日志好在哪？举一个 `jq`/`grep` 的具体优势。
4. trace_id 为什么必须用 contextvars 而不是全局变量？在并发下不这么做会出什么问题？
5. 日志的四个级别（DEBUG/INFO/WARNING/ERROR）各在什么场景用？为什么降级是 WARNING 不是 ERROR？
6. 哪些敏感信息绝不该进日志？`mask_secret` 解决什么问题？
7. （落地）kb-qa 的 `stream_ask` 现在多了哪几个结构化事件？怎么按 trace_id 还原一次问答链路？
