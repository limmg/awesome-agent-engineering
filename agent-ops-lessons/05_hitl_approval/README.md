# Lesson 05 — 人在环审批（HITL）：危险动作的门闸

> 本课目标：**用 langgraph `interrupt()` 给危险动作装审批门——暂停、等人、恢复**。把故障⑥后半（publish 未经批准直接执行）从「裸奔」变成「首次必审、批准后发布、否决走诚实收尾」，并支持跨进程恢复（审批可以隔夜）。
>
> 学完你能回答面试官那句：**「你的 Agent 能执行危险操作吗？怎么保证安全？」**——答案是人在环门闸：interrupt 暂停、状态落盘、批准后跨进程恢复执行；策略分层只拦不可重放且首次的动作，不把人变成橡皮图章，也不让 Agent 裸奔。

---

## 0. 起点：为什么 Agent 需要「中途暂停等人」

L04 给 publish 加了幂等键——挡住了「重复执行」。但幂等挡不住「首次但不该执行」（如：报告内容有错、不该发布）。这就是 L05 审批门要补的。

> 🎯 **核心认知**：请求模型没有「中途暂停等人」这回事——请求秒回。但**轨迹可以挂起几小时**：Agent 跑到 publish 节点，要不要发布需要人拍板，此时整个运行应该能暂停、等人、恢复。这是 Agent 特有的需求，kb-qa 这种线性链完全没有。

---

## 1. interrupt/resume 机制（实测 langgraph 1.2.7）

> ⚠️ **诚实标注（实测）**：以下行为在 langgraph 1.2.7 实测确认。

### 1.1 三步流程

```
① 第一次 ainvoke（跑到 publish）
   → 节点内调 interrupt({"action":"publish", "preview":...})
   → 返回 {'__interrupt__': [Interrupt(value=...)]}
   → state.next = ('publish',)（暂停在 publish）
   → checkpointer 存了中断状态

② 进程可以退出（审批可以隔夜）
   → 状态躺在 sqlite 里，不丢

③ 带 resume 值重新 ainvoke(Command(resume={"approved": True}))
   → interrupt() 返回 resume 值
   → publish 节点据此决定发布/否决
   → 继续到 END
```

### 1.2 实测验证

```python
# code.py 的最小可复现演示
r1 = await graph.ainvoke({"report": "..."}, config=cfg)
# r1 = {'__interrupt__': [Interrupt(value={'action':'publish',...})], ...}
state = await graph.aget_state(cfg)
# state.next = ('publish',)

r2 = await graph.ainvoke(Command(resume={"approved": True}), config=cfg)
# r2 = {'published': '✅ 已发布'}
```

关键：`interrupt()` 的返回值就是 `Command(resume=...)` 传入的那个值。节点据此分支。

---

## 2. publish 节点接 interrupt

```python
# publish.py make_publish_node（enable_hitl 时）
def publish_node(state):
    report = state["report"]
    if settings.enable_hitl and _needs_approval(thread_id, report):
        # interrupt 暂停：进程可退出
        decision = interrupt({
            "action": "publish_report",
            "content_preview": report[:200],
            "policy": settings.hitl_policy,
        })
        approved = isinstance(decision, dict) and decision.get("approved")
        if not approved:
            # 否决 → 诚实收尾（不发布，标 truncated）
            return {"publish_result": {"published": False, "rejected": True},
                    "truncated": True}
    # 批准（或无需审批）→ 执行 publish（幂等）
    result = publish_report(thread_id, report)
    return {"publish_result": result}
```

---

## 3. 审批策略分层（自主-控制主线的教科书）

| 策略 | 行为 | 适用 | 取舍 |
|---|---|---|---|
| `auto` | 全过（HITL 形同虚设） | 演示基线 / 低风险动作 | ✅ 快；🚫 等于没开 HITL |
| `first_only`（默认） | 仅首次发布审 | 最实用 | ✅ 幂等重放免审，不放过首次；🚫 内容大改（新 key）要再审 |
| `always` | 每次都审 | 高风险 | ✅ 最安全；🚫 每次都等人，延迟高 |

```python
def _needs_approval(thread_id, content):
    policy = settings.hitl_policy
    if policy == "auto": return False
    if policy == "always": return True
    # first_only：幂等重放（同 key 已发布）免审
    key = idempotency_key(thread_id, content)
    if any(h["key"] == key for h in get_publish_history(thread_id)):
        return False  # 幂等重放，免审
    return True  # 首次发布，必审
```

> 🎯 **核心认知**：`first_only` 的精妙在于它**复用了 L04 的幂等键**——幂等重放（同内容 no-op）天然免审，因为「反正不会真执行，审什么」。只有首次发布（会真执行副作用）才拦。这就避免了「幂等 no-op 还要人点确认」的橡皮图章，又不放过真正的首次发布。**L04 的幂等键是 L05 审批策略的地基。**

---

## 4. 服务化：SSE 审批事件 + API 端点

### 4.1 服务层恢复入口

```python
# service.py
async def submit_approval(thread_id, approved, comment="") -> dict:
    """提交审批，Command(resume=...) 恢复被 interrupt 暂停的 publish。"""
    result = await system.ainvoke(
        Command(resume={"approved": approved, "comment": comment}),
        config={"configurable": {"thread_id": thread_id}},
    )
    return result
```

### 4.2 API 轮询 + 提交

- SSE 新增 `approval_required` 事件（跑到 publish interrupt 时发）。
- `POST /api/approvals/{thread_id}` 提交批准/否决 → 调 `submit_approval`。
- `GET /api/tasks/{id}` 可查 `is_awaiting_approval`（轮询是否在等审批）。
- CLI 走 `input()`。

### 4.3 跨进程/跨重启恢复

> 💡 关键：审批可以**隔夜**。进程 A 跑到 publish interrupt 暂停后退出；进程 B（重启后）用同 thread_id 调 `submit_approval`，checkpointer 从 sqlite 读出中断状态，恢复执行。这是 `interrupt` + 持久 checkpointer 的组合威力——Agent 的运行不再受单次进程生命周期的限制。

---

## 5. 方案对比：怎么拦危险动作？

| 方案 | 做法 | 取舍 |
|---|---|---|
| ① **全自动** | 危险动作直接执行 | ✅ 快；🚫 事故自负（首次但不该执行的也执行了） |
| ② **全人审** | 每一步都等人确认 | ✅ 最安全；🚫 Agent 退化成草稿机（延迟从秒级变小时级） |
| ③ **策略门控**（本课主路线） | 只拦不可重放且首次的动作（first_only） | ✅ 自主性损失最小、只拦该拦的、支持跨进程恢复；🚫 策略判断要设计 |

**选 ③ 的理由**：方案 ① 把事故风险全留给生产，方案 ② 把 Agent 变成人肉执行器。策略门控的精髓是「**闸只拦该拦的**」——L04 幂等已挡重放，L05 只补「首次但不该执行」这一道。这是自主-控制主线的教科书案例：闸太紧 Agent 废掉，闸太松等于裸奔，分层策略找到了平衡点。

> 💡 **紧还是松？**（自主-控制主线）：`first_only` 是默认的平衡点——首次发布必审（紧，挡住首次风险），幂等重放免审（松，不让人变橡皮图章）。`always` 是「最紧」（高风险场景），`auto` 是「最松」（演示/低风险）。判断依据是「动作的不可逆性 + 频率」：不可逆 + 低频（如下单）用 always，不可逆 + 高频（如发布报告）用 first_only。

---

## 6. 跑起来

### `code.py` 演示

```bash
cd portfolio-projects/research-assistant
python ../../agent-ops-lessons/05_hitl_approval/code.py
```

演示：
1. **interrupt/resume 三场景**：暂停 ⏸️ → 批准 ✅ → 否决 🚫（诚实收尾）
2. **审批策略分层表**：auto / first_only / always

---

## 7. 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/research_assistant/publish.py` | `make_publish_node` 接 interrupt；新增 `_needs_approval`（策略判断） | `pytest tests/test_hitl.py -q` |
| `src/research_assistant/config.py` | **新增**：`enable_hitl`/`hitl_policy`（默认关 / first_only） | 改 `.env` |
| `src/research_assistant/service.py` | **新增**：`submit_approval`（Command(resume) 恢复）+ `is_awaiting_approval`（轮询） | 见下 |
| `tests/test_hitl.py` | **新增**：8 个测试（策略判断 + interrupt/resume 端到端 + 开关行为） | `pytest tests/test_hitl.py -q` |

### 验收

```bash
cd portfolio-projects/research-assistant

# 1. 全部测试绿（185 + 8 = 193）
python -m pytest -q
# 预期：193 passed

# 2. 开 HITL 后 publish interrupt 暂停
python -m pytest tests/test_hitl.py::test_publish_interrupts_for_approval -q
# 预期：passed（跑到 publish 时 state.next 含 publish）

# 3. 批准 → 发布；否决 → 诚实收尾
python -m pytest tests/test_hitl.py::test_publish_approved_then_publishes tests/test_hitl.py::test_publish_rejected_then_truncate -q
# 预期：passed

# 4. 开关关时不 interrupt（现状）
python -m pytest tests/test_hitl.py::test_hitl_off_no_interrupt -q
# 预期：passed
```

---

## 8. 本课在两条主线上的位置

- **爆炸半径主线**：把「危险副作用」的爆炸半径从「首次也会执行」（L04 只挡重放）进一步压到「首次必审，批准才执行，否决诚实收尾」。幂等（L04）+ 审批（L05）叠加，重放和首次两种风险都挡住了。
- **自主-控制主线**：这是本课的灵魂——闸太紧 Agent 废掉（全人审），闸太松等于裸奔（全自动）。`first_only` 策略是平衡点：只拦不可重放且首次的动作，复用 L04 幂等键让重放免审，不把人变橡皮图章。

---

## 🎯 面试话术

> 「我的 Agent 危险动作有人在环门闸：langgraph 的 `interrupt()` 在 publish 节点暂停，状态落进 checkpointer，批准后用 `Command(resume=...)` 跨进程恢复执行——审批可以隔夜，进程退出了重启也能接着审。
>
> 审批策略是分层的，这是自主-控制权衡的核心：默认 `first_only`——首次发布必审，后续幂等重放（同内容 no-op）免审。这个策略复用了我 L04 的幂等键：反正重放不会真执行，审什么？只拦会真执行的首次发布。这样既不放过首次风险，也不把人变成橡皮图章。
>
> 否决走诚实收尾——标 truncated 不发布，和 L01 的步数超限收尾是同一条路径。幂等（L04）挡重放，审批（L05）挡首次不该执行的，两者叠加才是完整的危险动作治理。闸太紧 Agent 废掉，闸太松等于裸奔，分层策略找到了平衡点。」
