# Lesson 09 练习

> 在 `research-assistant` 项目里验证 MCP client 集成，或改 `demo.py` 观察变化。

---

## 练习 1：让 kb_search 失败时优雅降级

看 `nodes.py` 里 `kb_raw = await kb_search(subtopic) if settings.enable_kb_search else ""`。故意把 `kb_mcp_server_path` 配成一个不存在的路径，跑一次研究，确认 Agent **不会崩**，而是降级为纯联网。

**思考**：为什么「调用远程 MCP 工具」必须假设它随时不可用？（server 是独立进程/远程服务，网络、启动、入库状态都可能失败。）远程工具的容错，是本地函数调用不需要操心、但分布式集成必须做的事。

---

## 练习 2：给 researcher 加第二个 MCP server

现在 Agent 只连了 kb-qa 一个 server。设想再接一个「公司内部 Wiki」的 MCP server。描述你要改动哪几处：工具装配、config 开关、失败降级。

**思考**：MCP 的价值是「加一个工具源 = 多连一个 server，Agent 主逻辑零改动」。对比传统做法：每加一个数据源都要改 Agent 的工具注册 + prompt + 重新测试。

---

## 练习 3：内部+外部双源的合并策略

`enable_kb_search=true` 时，researcher 会同时拿到内部知识库材料和联网结果。想想：如果两者冲突（内部文档说试用期 3 个月，某网页说行业惯例 6 个月），Agent 该怎么处理？

**思考**：多源研究的核心难点不是「拿到数据」，是「可信度排序与冲突消解」。内部知识库通常更权威（公司自己的制度），联网是补充行业背景——这个优先级应该体现在 prompt 里。

---

## ✅ 完成本课后，你应该能回答

1. MCP client 如何发现并调用远程 server 的工具？
2. Agent 工具集从「本地函数」扩展到「远程 MCP 工具」意味着什么？
3. 为什么远程工具调用必须做失败降级？本地函数为什么不用？
4. 两个已有项目通过 MCP 打通，证明了 MCP 的什么价值？（M+N 互操作）
