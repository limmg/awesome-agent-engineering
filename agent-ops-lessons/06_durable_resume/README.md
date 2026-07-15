# Lesson 06 — 断点续跑：崩溃后的重做量有界

> 本课目标：**把 checkpointer 从「被动存状态」升级为「任务级恢复语义」**——给任务一个注册表（jobs 表），崩溃后扫描孤儿任务、从 checkpoint 续跑，已完成的节点不重做、已执行的副作用靠 L04 幂等键不重放。把故障④（进程崩溃）的重做量从「全部」压到「最后一个未完成节点」。
>
> 学完你能回答面试官那句：**「你的 Agent 跑一半崩了怎么办？」**——答案是任务级恢复：jobs 注册表发现孤儿任务，checkpoint 续跑让重做量有界，副作用有幂等键不重放。账本管跨运行增量，checkpoint 管单次运行恢复，两层各管一段。

---

## 0. 起点：现状 checkpointer 躺在库里等于没有

L00 的 `baseline_chaos.json` 记录故障④（进程崩溃）结局是 `full_rerun`——**崩溃后从头全部重跑，重做量无界**。

> 🎯 **核心认知**：现状的 `AsyncSqliteSaver` 已经在每个超级步落盘 State——所以「状态没丢」。但**服务层没有任务注册**：崩溃后没人知道「哪些任务没跑完、该从哪继续」。checkpoint 躺在 sqlite 里，但没人去读它续跑。状态存了等于没存，因为没有「恢复语义」。

```
现状崩溃链：
  research_team(检索完成) → writer(💥进程被杀)
       ↓
  重启 → 用户重新提交 → 从头跑（research_team 的检索白做了）
       ↓
  重做量：全部（成本 ×2）
  副作用：如果有 publish，会重复发布（L04 幂等才挡住）
```

---

## 1. 任务注册表：给任务一个身份

```python
# jobs.py
CREATE TABLE jobs (
    task_id     TEXT PRIMARY KEY,   -- 任务身份
    thread_id   TEXT NOT NULL,      -- checkpointer 的 key（恢复用）
    topic       TEXT NOT NULL,
    status      TEXT NOT NULL,      -- pending/running/done/failed/interrupted
    created_at, updated_at, result_json, error
)
```

### 1.1 三步恢复语义

1. **提交即登记**：`submit_job(topic)` 创建 task_id + thread_id，状态 pending。
2. **完成即更新**：跑完更新 done + result；崩溃/中断更新 interrupted/failed。
3. **启动时扫描孤儿**：`find_orphans()` 找 running/interrupted 的任务，`recover_orphans()` 对每个调 `resume_job`。

### 1.2 长任务服务化

```python
# service.py
async def submit_research(topic, thread_id=None):
    """立即返回 task_id，后台跑（长任务异步化）。"""
    job = submit_job(topic, thread_id)
    # ... 后台跑，更新状态
    return {"task_id": job["task_id"], "thread_id": job["thread_id"]}
```

`POST /api/research` 立即返回 task_id，`GET /api/tasks/{id}` 查状态/取结果。同步 SSE 保留，长任务走异步。

---

## 2. checkpoint 续跑：已完成节点不重做

### 2.1 核心机制（实测 langgraph 1.2.7）

> ⚠️ **诚实标注（实测）**：以下行为在 langgraph 1.2.7 实测确认。

```python
# 恢复：同 thread_id，None 输入
result = await system.ainvoke(None, config={"configurable": {"thread_id": thread_id}})
```

`None` 输入告诉 langgraph「不传新输入，从最后 checkpoint 续跑」。实测结果：

```
崩溃前：research_team(✓完成) → writer(interrupt 暂停，模拟崩溃)
恢复后：research_team(call_count 不变=1，没重做!) → writer(重跑=2) → reviewer(=1)
```

### 2.2 「重做量=最后一个未完成节点」的精确含义

> 🎯 **核心认知（诚实，实测）**：checkpoint 续跑时，**中断前已完成的节点不重做**（research_team 的检索不重跑），但**中断所在的节点会从头执行一次**（writer 会重跑）。这不是「零重做」，而是「重做量 = 最后一个未完成节点」——从一个节点起算，而非从头。这就是「重做量有界」的精确含义。

```
裸奔崩溃：        research_team → writer(崩) → 重启 → research_team(重做) → writer → reviewer
                                  重做量 = 全部（research_team + writer）

checkpoint 续跑：  research_team → writer(崩) → 重启 → writer(重做) → reviewer
                                  重做量 = writer（最后一个未完成节点）
```

### 2.3 副作用不重放：靠 L04 幂等键

writer 重跑时，如果它内部调了 publish，会不会重复发布？**不会**——因为 L04 的幂等键：同 thread + 同内容 → no-op。这就是为什么 L04 必须先于 L06：幂等键是断点续跑不重放副作用的地基。

---

## 3. 与 frontier-L10 TaskLedger 的边界（重要，不重叠）

| 维度 | frontier-L10 TaskLedger（账本） | **本课 checkpoint 续跑（durable）** |
|---|---|---|
| 管什么 | **跨多次运行**的语义增量 | **单次运行**的执行恢复 |
| 场景 | 第三次运行接着第二次的结论做，不重复研究 | 进程崩在 writer，重启后从 checkpoint 续跑 |
| 层次 | 工作层（研究进度 TODO 树） | 执行层（图执行状态） |
| 重做对象 | 跨运行的「研究」工作 | 单次运行的「节点」执行 |
| 关系 | 互补不重叠——两层叠加才是完整的长任务能力 |

> 💡 一句话：**账本管「跨运行增量」，durable 管「单次运行恢复」**。第三次研究一个主题时，账本告诉你「前两次查到了什么」（不用重新研究），durable 告诉你「这次跑崩在 writer，从 writer 接着跑」（不用重做检索）。两层各管一段，叠加才完整。

---

## 4. 方案对比：怎么从崩溃恢复？

| 方案 | 做法 | 取舍 |
|---|---|---|
| ① **无恢复重头跑**（现状） | 崩溃后用户重新提交，从头跑 | ✅ 简单；🚫 重做量无界（成本×2），副作用重放（无幂等时） |
| ② **checkpoint 续跑**（本课主路线） | 同 thread None 输入恢复，已完成节点不重做 + 幂等键不重放副作用 | ✅ 重做量有界（最后一个未完成节点）、副作用安全、有任务注册表；🚫 需要 checkpointer + jobs 表 |
| ③ **事件溯源 / 工作流引擎**（Temporal 式） | 每步事件落盘，失败从事件日志重放，有补偿机制 | ✅ 最强（分布式、可回放、可补偿）；🚫 重（要编排服务、要写补偿），单体 Agent 用不上 |

**选 ② 的理由**：方案 ① 是现状（重做无界），方案 ③ 杀鸡用牛刀（Agent 是单进程，不是分布式工作流）。checkpoint 续跑 + 幂等键 + jobs 注册表，覆盖了单体 Agent 的崩溃恢复需求。Temporal/事件溯源在「讲概念」时提一句，说什么规模才需要（跨服务、跨团队、长周期的工作流编排）。

> 💡 **紧还是松？**（自主-控制主线）：恢复策略没有「紧松」的权衡——它是纯增益（崩溃总比不崩好）。但有个判断：哪些任务值得自动恢复？`recover_orphans` 默认恢复所有 running/interrupted，但生产上可能想加「过期不恢复」（如 24 小时前的孤儿任务可能已无意义，标 failed 而非续跑）。

---

## 5. 跑起来

### `code.py` 演示

```bash
cd portfolio-projects/research-assistant
python ../../agent-ops-lessons/06_durable_resume/code.py
```

演示：
1. **checkpoint 续跑**：research_team 崩溃前完成 → 恢复时不重做（call_count=1）；writer 中断点重跑一次（=2）。
2. **任务注册表**：提交 3 个任务，1 个 done / 1 个 running / 1 个 interrupted，`find_orphans` 找到 2 个待恢复。

---

## 6. 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/research_assistant/jobs.py` | **新增**：jobs 注册表（submit/update/get/find_orphans/list） | `pytest tests/test_jobs.py -q` |
| `src/research_assistant/config.py` | **新增**：`enable_job_registry`（默认关） | 改 `.env` |
| `src/research_assistant/service.py` | **新增**：`submit_research`（异步任务）/ `resume_job`（None 输入恢复）/ `recover_orphans`（启动扫描） | 见下 |
| `tests/test_jobs.py` | **新增**：11 个测试（注册表 CRUD + 孤儿扫描 + checkpoint 续跑不重做） | `pytest tests/test_jobs.py -q` |

### 验收

```bash
cd portfolio-projects/research-assistant

# 1. 全部测试绿（193 + 11 = 204）
python -m pytest -q
# 预期：204 passed

# 2. checkpoint 续跑：已完成节点不重做
python -m pytest tests/test_jobs.py::test_checkpoint_resume_does_not_redo -q
# 预期：passed（n1 call_count=1 没重做）

# 3. 孤儿任务扫描
python -m pytest tests/test_jobs.py::test_find_orphans_finds_running -q
# 预期：passed（running/interrupted 是孤儿，done 不是）

# 4. 开关关时 submit_research 退化为 invoke
python -m pytest tests/test_jobs.py::test_submit_research_no_registry_degrades_to_invoke -q
# 预期：passed（jobs 表为空，没登记）
```

---

## 7. 本课在两条主线上的位置

- **爆炸半径主线**：把「中途崩溃」的爆炸半径从**无界**（重做全部，成本×2，副作用重放）压到**有界**（重做量=最后一个未完成节点，副作用靠幂等键不重放）。这是「重做量有界」的精确含义。
- **自主-控制主线**：恢复策略是纯增益，但「哪些任务值得自动恢复」有判断空间（过期孤儿可能不恢复）。与 frontier-L10 账本的边界要讲清——账本管跨运行增量，durable 管单次运行恢复，两层各管一段。

---

## 🎯 面试话术

> 「我的 Agent 崩溃恢复是任务级的：jobs 注册表登记每个任务（task_id/thread_id/status），启动时 `find_orphans` 扫描 running/interrupted 的孤儿任务，对每个调 `resume_job` 续跑。
>
> checkpoint 续跑的机制是同 thread_id 以 None 输入重新 ainvoke——langgraph 从最后 checkpoint 恢复。我实测过：中断前已完成的节点不重做（researcher 的检索不重跑），中断所在的节点会从头执行一次。所以重做量不是零，而是『最后一个未完成节点』——这就是『重做量有界』的精确含义。
>
> 副作用不重放，靠的是 L04 的幂等键——writer 重跑时如果调了 publish，同 thread+同内容的幂等键返回 no-op。这就是为什么幂等必须先于恢复做：幂等键是断点续跑不重放副作用的地基。
>
> 这套和 frontier-L10 的 TaskLedger 不重叠：账本管『跨多次运行的语义增量』（第三次研究接着第二次的结论），checkpoint 管『单次运行的执行恢复』（这次崩在 writer 从 writer 接着跑）。两层各管一段，叠加才完整。」
