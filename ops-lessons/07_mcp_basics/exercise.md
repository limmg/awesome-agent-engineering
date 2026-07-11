# Lesson 07 练习

> 改 `code.py` 里的代码，运行 `python code.py` 观察变化。本课依赖 mcp SDK（已装）。

---

## 练习 1：给 server 加第三个工具

在 `build_server()` 里加一个 `upper(text: str) -> str` 工具（把文本转大写），重跑 client，确认 `list_tools` 发现 3 个工具、能调用 `upper`。

```python
@mcp.tool()
def upper(text: str) -> str:
    """把文本转成大写。"""
    return text.upper()
```

**思考**：你只改了 server，client 代码一行没动，就自动发现了新工具——这就是 MCP **动态发现**的价值。对比传统 function calling：加个工具要改 host 的工具注册代码、改 prompt、重新部署。MCP 把「工具实现」和「工具消费」彻底解耦。

---

## 练习 2：观察「工具描述」如何影响 LLM 的选用

MCP tool 的 `description` 是给 LLM 看的——LLM 靠它判断「该不该调这个工具」。把 echo 的描述改成模糊的「一个工具」，看看（在真实 host 里）LLM 还能不能正确选用。

```python
@mcp.tool()
def echo(text: str) -> str:
    """一个工具。"""   # ← 描述太模糊
```

**思考**：工具描述是 MCP 工程化的关键——**描述写得好，LLM 才会正确选用；写得差，LLM 乱调或不用**。这就是为什么 L08 的 `search_knowledge_base` 工具描述要写清「查什么、返回什么、什么时候用」。MCP 不是「接上就能用」，工具的「可发现性」要靠描述质量。

---

## 练习 3：返回结构化数据（不只是字符串）

现在的工具都返回字符串。MCP 支持返回结构化结果。把 `add` 改成返回带元数据的结果：

```python
@mcp.tool()
def add(a: int, b: int) -> dict:
    """两数相加，返回和与计算时间。"""
    import time
    return {"sum": a + b, "computed_at": time.time(), "inputs": [a, b]}
```

重跑，看 client 怎么收到结构化数据。

**思考**：结构化返回让工具结果能被 host 程序化处理（而不是 LLM 再解析字符串）。L08 的 `search_knowledge_base` 会返回带 `source`/`section` 的结构化材料，让调用方知道「这个答案来自哪份文档」。

---

## 练习 4（进阶）：用 MCP Inspector 调试 server

MCP 官方有个可视化调试工具 `mcp inspector`，能像 Postman 一样手动调你的 server：

```bash
# 装 inspector（需 Node.js）
npx @modelcontextprotocol/inspector python code.py --server
# 打开浏览器看到的界面，能手动 list_tools / call_tool
```

**思考**：Inspector 是 MCP 开发的「Postman」——不用写 client 就能测 server。L08 封装 kb-qa server 后，README 会让你用 inspector 验证 `search_knowledge_base` 能不能对「试用期多久」返回材料。这是 MCP 生态的工程红利：工具标准化后，配套调试/监控工具自然就有了。

---

## ✅ 完成本课后，你应该能回答

1. MCP 解决什么问题？M×N 变成 M+N 是怎么做到的？（USB 类比）
2. tools / resources / prompts 三种能力的区别？哪个最高频？
3. stdio / SSE / streamable HTTP 三种传输各适合什么场景？
4. MCP 和 Function Calling 是替代关系吗？它们怎么配合？
5. client 连上 server 后的标准流程是什么？list_tools 为什么重要（动态发现）？
6. 工具的 description 为什么重要？（影响 LLM 选用）
7. （实操）你跑通的 echo/add，client 是怎么发现并调用的？stdio 传输的数据流是什么样？
