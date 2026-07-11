# Lesson 05 — 反思进研究回路：从「重写报告」到「修正结论」

> 本课目标：**把 L04 的 Reflexion 机制接进 research-assistant，把现有 reviewer 从单通道（只改文字）升级为双通道（文字重写 + 事实修正），让 Agent 发现新旧信息冲突时能定向补研并在报告中写修正说明。**

学完你能回答：**「你的 Agent 怎么修正错误结论？」**——不只改错字，还改错误认知。

---

## 0. 起点：现有 reviewer 的局限

research-assistant 现有的 reviewer（阶段 2）只做一件事：**评估报告的文字质量**——结构完不完整、表述专不专业。不合格就让 writer 重写。

```
现有 reviewer（单通道）：
  report 不合格 → "结构不完整" → writer 重写（改文字）
  
  🚫 不能做：发现"结论过时"→ 重新研究
  🚫 不能做：发现"新旧信息冲突"→ 判断采信谁
```

**问题**：硬任务要求"发现新信息与旧结论冲突时要修正并说明为什么"。现有 reviewer 根本不碰事实——它只看报告写得好不好，不看报告里的结论对不对。

本课升级为**双通道**：文字通道（现状保留）+ 事实通道（新增）。

---

## 1. 双通道 reviewer

```
                    ┌─────────── reviewer ───────────┐
                    │                                 │
     report ───────▶│  事实通道（新增）                │
                    │  新 findings vs 记忆旧结论       │
                    │  冲突？ ──是──▶ re_research      │──▶ research_team（定向补研）
                    │    │ 否                          │
                    │    ▼                             │
                    │  文字通道（现有）                │
                    │  结构/表述合格？                 │
                    │  不合格 ─▶ rework                │──▶ writer（重写）
                    │    │ 合格                         │
                    │    ▼                             │
                    │  pass                            │──▶ END
                    └─────────────────────────────────┘
```

| 通道 | 检测什么 | 不通过时 | 路由到 | 防死循环 |
|---|---|---|---|---|
| 事实通道（L05 新增） | 新 findings 与记忆旧结论冲突 | 生成定向补研问题 | research_team | `re_research_count >= max_re_research` |
| 文字通道（阶段 2） | 报告结构/表述质量 | 带 feedback | writer | `rewrite_count >= max_rewrites` |

### 事实通道优先

为什么事实通道优先于文字通道？因为**事实错了文字再漂亮也没用**。先修正认知（补研），再修文字（重写）。如果先重写文字，writer 可能基于错误结论写出"漂亮的错误报告"。

### 与硬任务的关系

硬任务要求"发现新信息与旧结论冲突时修正并说明为什么"。这条要求完全由事实通道实现：
1. reviewer 检测到新 findings 与记忆旧结论冲突
2. 生成定向补研问题（"验证 X 到底对不对"）
3. 路由回 research_team 用补研问题做子题
4. 补研结果回流，writer 在报告中写"修正说明"（旧结论/新证据/为何采信新的）

---

## 2. 冲突检测：check_conflicts

### 核心逻辑

```python
def check_conflicts(findings, mem_store, llm):
    for finding in findings:
        # 1. recall 旧记忆
        old = mem_store.recall(finding)
        # 2. LLM judge：一致 / 冲突 / 无关
        verdict = llm.judge(finding, old)
        if verdict == "冲突":
            conflicts.append(finding)
            # 3. 生成定向补研问题
            queries.append(llm.generate_question(finding, old))
    return {"conflicts": conflicts, "queries": queries}
```

### LLM judge 的判断标准

给 LLM 新发现和旧结论，让它判断三者之一：
- **一致**：新发现支持旧结论（无冲突）
- **冲突**：新发现与旧结论矛盾（需要修正）
- **无关**：新发现和旧结论讲的是不同方面（无冲突）

### 降级路径

无 LLM 时用关键词检测：finding 含"修正""实际上""并非""错误"等冲突信号词 → 疑似冲突。粗糙但能跑（教学演示用，生产必须用 LLM judge）。

---

## 3. 流派对比

**问题**：Agent 发现结论可能过时/错误时，怎么修正？

| 流派 | 做法 | 取舍 |
|---|---|---|
| ① 不修正（现状） | reviewer 只看文字，不管事实 | ✅ 简单；🚫 结论过时也不改 |
| ② 全量重查 | 每次都从头重新研究 | ✅ 一定最新；🚫 成本高、无增量 |
| ③ 冲突触发定向补研（本课选它） | 只在检测到冲突时补研冲突点 | ✅ 精准、成本低；🚫 依赖冲突检测质量 |
| ④ 定时刷新 | 定期重新研究所有主题 | ✅ 系统性；🚫 僵化、不响应实时冲突 |

**选 ③ 的理由**：硬任务的核心是"增量"——不是每次全查，是在有冲突时精准补。这和 L01 的记忆系统天然配合：有记忆才知道新旧冲突（没记忆就全是"新的"，无所谓冲突）。成本可控：只在冲突时补研，不是每次都补。

---

## 4. 定向补研：research_team 的升级

research_team 节点升级：检测到 `re_research_queries` 时，用它们做子题（而非重新 split）。

```python
async def research_team(state):
    re_queries = state.get("re_research_queries", [])
    if re_queries:
        # 定向补研：用冲突生成的补研问题作为子题
        sub_result = await research_subgraph.ainvoke({
            "topic": topic,
            "subtopics": re_queries,  # 直接用补研问题
            ...
        })
        return {"findings": sub_result["findings"]}  # 追加到现有 findings
    # 正常研究
    ...
```

### 关键设计：findings 是追加不是覆盖

`findings` 字段用 `operator.add` reducer，补研结果会**追加**到现有 findings，不覆盖。这样 writer 能看到"原始发现 + 补研发现"，在报告中写修正说明。

### writer 的修正说明

writer 检测到 `conflicts` 字段时，prompt 加修正说明要求：

```
📝 修正说明（请在报告中附「修正说明」部分，说明旧结论/新证据/为何采信新的）：
  - 新发现「MCP 基于 JSON-RPC」与旧结论「MCP 基于 gRPC」冲突
```

---

## 5. 防死循环

双通道各有计数器：
- 文字通道：`rewrite_count >= max_rewrites`（默认 3）→ 强制 pass
- 事实通道：`re_research_count >= max_re_research`（默认 2）→ 强制 pass

两个都超限时强制通过（不能再重写也不能再补研）。这保证了系统最终会结束，不会无限循环。

### review_route 的三路路由

```python
def review_route(state):
    decision = state["review_decision"]
    if decision == "pass":
        return END
    if decision == "re_research" and re_research_count <= max_re_research:
        return "research_team"  # 事实冲突 → 补研
    if decision == "rework" and rewrite_count < max_rewrites:
        return "writer"  # 文字不合格 → 重写
    return END  # 超限 → 结束
```

---

## 6. 落地清单

### 改了哪些文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/research_assistant/state.py` | 加 `conflicts`/`re_research_count`/`re_research_queries` | 双通道事实修正的 State 字段 |
| `src/research_assistant/config.py` | 加 `max_re_research` | 补研次数上限（防死循环） |
| `src/research_assistant/nodes.py` | reviewer 升级双通道 + `check_conflicts` + `review_route` 三路 | 事实通道检测冲突→定向补研 |
| `src/research_assistant/nodes.py` | research_team 支持补研子题 | 冲突时用补研问题做子题 |
| `src/research_assistant/nodes.py` | writer 加修正说明 prompt | 冲突时报告附修正说明 |
| `src/research_assistant/graph.py` | 条件边升级三路 | pass/rework/re_research |
| `src/research_assistant/service.py` | `_initial_state` 加新字段 | |
| `tests/test_nodes.py` | +6 个测试 | 双通道路由 + 冲突检测 |

### 如何验证

```bash
cd portfolio-projects/research-assistant

# 1. 全量测试（56 原有 + 6 新增 = 62 全绿）
.venv/Scripts/python.exe -m pytest tests/ -q
# 预期：62 passed

# 2. 演示冲突检测
cd ../../frontier-lessons/05_reflection_research
PYTHONIOENCODING=utf-8 ../../.venv/Scripts/python.exe code.py
# 预期：新发现与旧结论冲突 → 检测到 → 生成补研问题

# 3. 真实跑（需 ENABLE_MEMORY=true + API key）
# 构造一条与记忆旧结论冲突的假搜索结果，跑硬任务
# 报告里应出现「修正说明」（旧结论/新证据/为何采信新的）
```

---

## 7. 本课在两条主线上的位置

- **评估主线**：本课引入了"冲突检测准确率"和"修正有效性"两个可量化点——冲突检测对不对（误报/漏报）、修正后报告质量是否提升。L08 的 TrajectoryEvaluator 会把它们纳入轨迹指标。
- **上下文工程主线**：双通道 reviewer 是上下文工程的**判断层**——reviewer 要同时处理"报告文本"（当前上下文）和"记忆旧结论"（外部存储调回），判断一致性。这是 L01-L04 机制的协同：记忆提供旧结论、Reflexion 提供反思框架、双通道把反思落到具体的事实修正。

---

## 🎯 面试话术

> 「我的 reviewer 有双通道：文字通道管报告质量（不合格→重写），事实通道管结论正确性（新旧冲突→定向补研）。冲突检测用 LLM judge 判断新发现和记忆旧结论是一致/冲突/无关，冲突时生成补研问题回到 research_team 验证，writer 在报告里写修正说明——旧结论/新证据/为何采信新的。防死循环靠两个计数器：重写和补研各有上限。Agent 不只改错字，还改错误认知。」
