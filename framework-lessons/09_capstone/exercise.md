# Lesson 09 练习 — 毕业项目：LangGraph 研究助手

> 这是框架课程的毕业项目。练习重点是"扩展图"和"对比手写版"，为简历和面试做准备。

---

## 练习 1：把 Mermaid 图可视化（5 分钟）

运行 `code.py`，复制打印出的 Mermaid 代码，粘贴到 [mermaid.live](https://mermaid.live)。

**观察**：
- 图有几个节点？几条边？
- 条件边和回路在哪里？
- 对比你 Agent L09 手写时"读代码才能理解流程"——图的视觉化价值有多大？

> 面试时能画出这张图并解释数据流，是高级候选人的表现。

---

## 练习 2：加一个"报告审查"节点（核心扩展练习，20 分钟）

当前图是 `research → report → END`。加一个 `review` 节点，审查报告质量：

```
research → report → review →(条件)→ END（合格）
                              → research（不合格，重新搜索补充）
```

要求：
1. 定义 `review` 节点：让 LLM 检查报告是否信息充分、有无明显错误
2. 在 State 里加一个 `review_passed: bool` 字段
3. 用条件边：合格 → END，不合格 → 回到 research
4. 设置最大重审次数（防止死循环）

**思考**：这个扩展在手写 Agent L09 的 while 循环里有多难？（对比图的"加节点+连边"）

> 这就是图的杀手锏：扩展只需要加节点和边，不用重构整个循环逻辑。

---

## 练习 3：对比手写版和图版本的报告质量（10 分钟）

用同一个研究主题，分别跑：
- `agent-lessons/09_capstone/code.py`（手写 ReAct 循环）
- `framework-lessons/09_capstone/code.py`（LangGraph 图）

**对比**：
1. 两个版本搜索了几次？报告质量孰优？
2. 哪个版本的搜索过程更清晰？（看打印的轨迹）
3. 如果搜索限流了，两个版本的恢复能力如何？

> 两者原理相同（都是搜索→收集→报告），差异在工程结构。报告质量主要取决于 LLM 和搜索结果，而非用循环还是图。

---

## 练习 4：换一个研究主题测试泛化性（5 分钟）

把 `part_2_research` 的 topic 换成你感兴趣的领域，如：
- "2025 年大模型发展的关键趋势"
- "Python 异步编程的最佳实践"
- "向量数据库的选型对比"

观察助手能否自主规划搜索策略、生成合理报告。

**注意**：DuckDuckGo 偶尔限流，如果连续"无结果"，等几分钟或换关键词。

---

## 练习 5：给简历写项目描述（求职准备，15 分钟）

基于本课项目，写一段简历项目描述。要求：
- 突出技术深度（不要只写"用 LangGraph 做了个 Agent"）
- 体现你懂原理（手写过 vs 框架版的对比认知）
- 量化（节点数、搜索轮数、对比手写省了多少代码）

参考模板：
```
基于 LangGraph 的智能研究助手
- 用 StateGraph 设计 N 节点 Agent 图（research→tools→report），
  集成 web_search 实现自主多轮联网搜索，输出结构化研究报告
- 用条件边替代手写版的字符串检测，Checkpointer 实现跨会话记忆
- 对比手写 ReAct 循环，流程可视化、代码量从 ~X 行降到 ~Y 行
```

把它改成你自己的话，确保面试时能解释每个技术选型的理由。

---

## 练习 6（进阶）：接入 RAG 知识库作为工具（衔接 Agentic RAG）

参考 Agent L07（Agentic RAG），把 RAG 课程建好的知识库（员工手册）包装成一个 `search_knowledge_base` 工具，接到研究助手图里：

```python
@tool
def search_knowledge_base(query: str) -> str:
    """搜索公司内部知识库（员工手册等）。查内部政策时使用。"""
    # 用 L04 的 retriever 检索
    docs = retriever.invoke(query)
    return "\n".join(d.page_content for d in docs)
```

这样助手就同时具备"查内部知识 + 联网搜索"两种能力——这就是 Agent L07 的 Agentic RAG 思路在框架里的落地。

---

## 思考题（不写代码）

1. **为什么用自定义 State 而非 MessagesState？** 如果只用 MessagesState，topic 和 report 存哪里？（提示：能不能塞进 messages？为什么不优雅）

2. **条件边 `{END: "report"}` 这个映射是什么意思？** 为什么要把默认的 END 路由到 report 节点？

3. **这个图相比 Agent L09 手写循环，最大的工程价值是什么？** 如果产品要求加"报告审查""多语言""用户审批"三个新功能，哪个版本更容易扩展？

---

## 完成标志

- [ ] 能画出研究助手图的完整结构（节点+边+回路）
- [ ] 跑通了自主搜索 + 报告生成的完整流程
- [ ] 理解自定义 State 的价值（携带 topic + report）
- [ ] 理解条件边如何替代字符串检测
- [ ] 能向别人解释这个项目的技术选型（简历/面试级）

---

## 🎉 框架课程毕业

完成全部 9 课后，你已经拥有：
- 📘 RAG 手写课程（9课）：从 embedding 到评估的完整原理
- 🤖 Agent 手写课程（9课）：从 Function Calling 到多智能体
- 🔧 框架进阶课程（9课）：LangChain + LangGraph 工程化

**共 27 课，3 个可写进简历的作品。** 下一步：跑通所有毕业项目、写简历、准备面试。
