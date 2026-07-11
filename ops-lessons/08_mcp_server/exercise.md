# Lesson 08 练习

> 改 `code.py`（自包含教学版）观察变化，或在 kb-qa 项目里验证生产版 `mcp_server.py`。

---

## 练习 1：给 server 加第二个工具 `ask_knowledge_base`

L08 讲了两个粒度：`search`（只返材料）vs `ask`（检索+生成完整答案）。在 `code.py` 的 `build_server()` 里加一个 `ask_knowledge_base(question)`，用假检索拿材料后拼一句「根据材料，……」的答案返回。

```python
@mcp.tool()
async def ask_knowledge_base(question: str) -> str:
    """检索 + 生成完整答案（适合只想拿答案、不想自己拼 prompt 的 host）。"""
    hits = _fake_retrieve(question)
    return f"根据知识库材料：{hits[0]['content']}"
```

**思考**：为什么 L09 的 Agent 集成默认推 `search` 而非 `ask`？（提示：Agent 要「原料」自己综合，不要「成品」——给工具使用者留决策空间。）

---

## 练习 2：把工具描述改烂，观察后果

把 `search_knowledge_base` 的 docstring 改成模糊的「查东西的工具」。在真实 host（Claude Desktop）里注册后，观察 LLM 还会不会在「问公司制度」时正确选它。

**思考**：MCP 工具的 `description` 是 LLM 选用工具的唯一依据。生产版描述写清了「查什么/返回什么/何时用」——这不是文档，是让工具「可被正确调用」的功能代码。

---

## 练习 3：教学版 vs 生产版的差距在哪？

对比 `code.py`（假检索）和 `portfolio-projects/knowledge-base-qa/mcp_server.py`（真 KBRetriever）。列出生产版多做了哪些事：

- 同步检索为什么要 `asyncio.to_thread` 包一层？（教学版为什么不用？）
- BM25 索引为什么要单例化（建一次答多次）？
- stdio vs streamable HTTP 传输，kb-qa 为什么两种都支持？

**思考**：教学版让你看清「封 tool」的骨架；生产版的复杂度全在「让它在真实并发/启动成本下也能用」。这正是 demo 和生产的分界。

---

## 练习 4（进阶）：注册进 Claude Desktop 真跑一次

按 README 的 `claude_desktop_config.json` 片段，把 `mcp_server.py` 注册进 Claude Desktop（需已入库 + ZHIPUAI_API_KEY），重启后问「云帆科技试用期多久」，观察 Claude 是否自动调用了 `search_knowledge_base`。

**思考**：这一步验证的是 MCP 的终极价值——**你没写一行 host 代码，Claude 就用上了你的知识库**。这就是「M+N 集成」落到实处的样子。

---

## ✅ 完成本课后，你应该能回答

1. 为什么已有 HTTP API 还要封 MCP？（接每个 host 的成本差异）
2. 把业务能力映射成 MCP tool 要设计哪三样东西？
3. `search` 和 `ask` 两个粒度分别给谁用？为什么默认推 `search`？
4. 同步检索在 async MCP 框架里为什么要 `to_thread`？
5. stdio 和 HTTP 传输各适合什么部署场景？
