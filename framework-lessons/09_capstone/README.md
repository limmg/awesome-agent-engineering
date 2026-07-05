# Lesson 09 — 毕业项目：LangGraph 研究助手

> **本课定位**：框架课程的**收官之作**。把你 Agent L09 手写的研究助手（一个 ReAct `while` 循环 + 手动 `FINAL_REPORT` 检测 + 手动报告生成），用 LangGraph 重做成**多节点图结构**，并综合 L06（StateGraph）+ L07（@tool）+ L08（记忆/HITL）的全部技术。
>
> **映射的手写课**：`agent-lessons/09_capstone`（手写 `run_research_agent`）+ `agent-lessons/07_agentic_rag`（RAG 作为工具的思路）

---

## 一、回顾：你 Agent L09 手写的研究助手

打开 `agent-lessons/09_capstone/code.py`，你的核心是 `run_research_agent`：

```python
def run_research_agent(client, topic, max_steps=8):
    messages = [system, user]
    for step in range(max_steps):
        msg = client.chat.completions.create(messages=messages, tools=TOOLS_SPEC, ...)
        if "FINAL_REPORT" in msg.content:     # ← 手动字符串检测"该出报告了"
            break
        if msg.tool_calls:
            result = execute_function(...)    # ← 手动执行搜索
            messages.append({"role": "tool", ...})
    report = generate_report(topic, collected_info)   # ← 循环外单独生成报告
```

这是一个单层的 `for` 循环，把"搜索"和"生成报告"混在一起，靠字符串 `"FINAL_REPORT"` 来判断阶段切换。

**痛点**：
1. **阶段切换靠字符串检测**——脆弱（模型写错一个字就失效）。
2. **流程不可视**——"先搜索、搜够再出报告"这个逻辑藏在循环里。
3. **报告生成在循环外**——结构上割裂，难扩展（比如想加"审查报告"步骤）。

---

## 二、LangGraph 版的图设计

本课用一张多节点图重写，结构清晰可见：

```
                  ┌──────────────────────────────────────┐
                  │                                      │
                  ▼                                      │
START ──▶ ┌──────────────┐  有tool_calls(要搜索)  ┌─────┴───┐
          │  research    │───────────────────────▶│  tools  │
          │ (调模型+决策) │                        │(执行搜索)│
          └──────┬───────┘                        └─────────┘
                 │ 没tool_calls(搜够了)
                 ▼
          ┌──────────────┐
          │  report      │────────▶ END
          │ (生成报告)    │
          └──────────────┘
```

### 三个节点

| 节点 | 作用 | 对应 Agent L09 手写的什么 |
|------|------|--------------------------|
| `research` | 调模型（绑定 web_search 工具），决定"继续搜"还是"够了" | 循环里的 `client.chat.completions.create` |
| `tools` | 执行 web_search，结果塞回 messages | `execute_function` + `messages.append` |
| `report` | 把搜集的信息整理成结构化报告 | 循环外的 `generate_report` |

### 两条边 + 一个回路 + 一个条件

- `START → research`：入口
- `research →(条件)`：模型要搜索去 `tools`，搜够了去 `report`
- `tools → research`：搜索结果喂回去，**这就是 while 循环**（L06 学的回路）
- `report → END`：报告生成完结束

**对比 Agent L09**：你的 `for` 循环 + `"FINAL_REPORT"` 字符串检测，现在变成了**条件边**（模型不调工具了 = 搜够了 → 去 report）。结构化、不脆弱、可视化。

### 自定义 State —— 为什么不用 MessagesState？

Agent L09 需要记住"研究主题"和"最终报告"，这些不只是 messages。所以本课用**自定义 State**：

```python
class ResearchState(TypedDict):
    topic: str               # 研究主题（report 节点要用）
    messages: Annotated[list, add_messages]  # 对话历史（自动追加）
    report: str              # 最终报告（report 节点产出）
```

对比 L06 的 `MessagesState`（只有 messages），自定义 State 能携带**任意业务字段**——这是真实项目必需的能力。

---

## 三、综合了哪些技术（本课是框架课程的集大成）

| 技术 | 来自哪课 | 在本课怎么用 |
|------|---------|-------------|
| StateGraph + 节点 + 条件边 | L06 | 整张图的骨架 |
| `@tool` 装饰器 | L07 | 定义 `web_search` 工具 |
| `ToolNode` + `tools_condition` | L06/L07 | 自动执行搜索 + 路由 |
| 自定义 State | 本课新增 | 携带 topic + report 字段 |
| Checkpointer 记忆 | L08 | `InMemorySaver` 让研究助手记住跨轮对话 |
| Mermaid 可视化 | 本课新增 | `draw_mermaid()` 打印图结构 |

**这就是为什么 L06-L08 要先学**——它们是毕业项目的积木。你现在把它们拼起来。

---

## 四、Agent L09 的循环 vs 本课的图：终极对比

| 环节 | Agent L09 手写 | 本课 LangGraph 图 |
|------|---------------|------------------|
| 搜索循环 | `for step in range(max_steps)` | `tools → research` 回路 |
| 阶段切换 | 检测字符串 `"FINAL_REPORT"` | 条件边（无 tool_calls → report）|
| 执行搜索 | `execute_function` + 手动 append | `ToolNode` 自动 |
| 报告生成 | 循环外单独调用 | 独立的 `report` 节点 |
| 状态管理 | 手动维护 messages + collected_sources | 自定义 State 自动 |
| 流程可视 | 无 | Mermaid 图 |
| 记忆 | 无（每次重新开始）| Checkpointer 跨轮记忆 |
| 可扩展 | 改循环 | 加节点 + 连边 |

**核心不变的是研究助手的原理**（搜索→收集→报告）。图让它结构化、可视化、可扩展、可记忆。

---

## 五、运行本课

```bash
python framework-lessons/09_capstone/code.py
```

你会看到：
1. 图结构的 Mermaid 可视化（对比手写的"读代码才知道流程"）
2. 研究助手自主搜索一个主题（多轮 web_search 循环）
3. 自动生成结构化研究报告
4. Checkpointer 记忆演示（追问能接上下文）

> 💡 本课用 DuckDuckGo 联网搜索（和 Agent L09 一样，免费无 key）。偶尔会限流返回"无结果"，Agent 会自动换关键词重试——这也是真实工程的常态。

---

## 六、简历价值

这个项目可以写进简历，建议这样描述：

> **基于 LangGraph 的智能研究助手**：用 StateGraph 设计多节点 Agent 图（research → tools → report），集成 web_search 工具实现自主多轮联网搜索，Checkpointer 实现跨会话记忆，输出结构化研究报告。对比手写 ReAct 循环，图结构让流程可视化、阶段切换从字符串检测升级为条件边路由。

面试时能说的深度点：
- 为什么用图而非 while 循环（可视化、可扩展、可持久化）
- 条件边如何替代脆弱的字符串检测
- 自定义 State vs MessagesState 的取舍
- `@tool` + `ToolNode` + `tools_condition` 各自的职责
- 真实遇到的问题（搜索限流、模型参数错误）及处理

---

## 七、小结：框架课程全部完成 🎉

学完 L01-L09，你已经把**手写的 RAG（9课）+ 手写的 Agent（9课）+ 框架工程化（9课）= 27 课**全部跑通。你现在能：

- 说清 LangChain 与 LangGraph 的分工与取舍
- 用 LCEL 组装 RAG Chain，用 StateGraph 设计状态化 Agent
- 回答"框架替你做了什么、隐藏了什么、何时绕回手写"——高级候选人才答得上
- 拥有 3 个可写进简历的作品（RAG 助手 / 手写 Agent / LangGraph 研究助手）

**下一步建议**：
1. 把三个毕业项目都跑一遍，确保能演示
2. 用 LangSmith 给研究助手加可观测性（trace 每步耗时/Token）
3. 探索部署：LangGraph Studio / FastAPI 服务化
4. 关注 LangChain 1.x 的持续迁移（community sunset / create_react_agent → create_agent）

恭喜完成全部课程！
