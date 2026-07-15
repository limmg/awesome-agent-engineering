# Lesson 04 — 副作用与幂等：能重放的才敢自动化

> 本课目标：**引入第一个副作用工具 `publish_report` 并治理它——幂等键（同内容重放 no-op）、重放安全、dry-run 演练**。把故障⑥前半（reviewer 打回重写导致重复发布）从「事故」变成「幂等 no-op」。
>
> 学完你能回答面试官那句：**「你的 Agent 能执行危险操作吗？怎么保证不重复？」**——答案是副作用三级分类 + 幂等键：只读/可重放/不可重放，不可重放的动作必须有 `hash(thread_id+内容指纹)` 的幂等键，重跑、打回重写、断点恢复都可能重放路径，幂等是敢自动化的前提。

---

## 0. 起点：现状「没出过事」是因为「没做过危险的事」

L00 的 `baseline_chaos.json` 记录故障⑥前半的裸奔结局：reviewer 打回重写导致 publish 被走到 **2 次**，重复发布。

> 🎯 **核心认知**：现状 research-assistant 全是**只读工具**（search/browser），所以「没出过事」是因为「没做过危险的事」。一旦加发布动作（写 outputs/ + 模拟对外发布），重复执行就是事故——reviewer 打回重写会让 publish 被走到两次，断点续跑（L06）会重放已执行的副作用。**幂等是敢自动化的前提。**

---

## 1. 工具副作用三级分类

| 级别 | 例子 | 重复执行的后果 | 需要幂等？ |
|---|---|---|---|
| ① **只读** | search / browser | 无害（无副作用） | 不需要 |
| ② **可重放** | 写本地文件 | 覆盖无害（最终状态一致） | 不严格需要 |
| ③ **不可重放** | 发布 / 发邮件 / 下单 | **事故**（每次都有外部副作用） | **必须** |

> 💡 这个分类决定了治理力度：① 不用管，② 靠「最终一致」自然兜底，③ 必须有幂等键 + 审批门（L05）。`publish_report` 是 ③——它写 outputs/ + sqlite 发布注册表，模拟「对外发布」，每次执行都有外部可见的效果。

### 三种会重放 ③ 的场景

1. **reviewer 打回重写**：writer 重写后内容可能没变（reviewer 要求的是别处），publish 又被走到。
2. **断点续跑（L06）**：进程崩在 publish 后、END 前，重启续跑会再走到 publish。
3. **手动重试**：用户觉得「上次没成功」（其实成功了）又触发一次。

没有幂等键，这三种场景都会重复发布。

---

## 2. 幂等键：hash(thread_id + 内容指纹)

```python
# publish.py
def idempotency_key(thread_id: str, content: str) -> str:
    """thread_id + 内容指纹 → 幂等键。"""
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    thread_hash = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:8]
    return f"{thread_hash}:{content_hash}"
```

### 2.1 为什么用内容指纹而不只是 thread_id

如果只用 `thread_id` 做幂等键，reviewer 打回重写后的「改进版」会被当成重复不发布——但那是用户想要的更新。**内容指纹让「内容相同才算重复」**：

- 同 thread + 同内容 → 同一 key → 第二次 no-op（幂等重放）
- 同 thread + 不同内容（改进版）→ 不同 key → 算新发布
- 不同 thread + 同内容 → 不同 key → 各自发布（会话隔离）

### 2.2 sqlite 发布注册表

```python
CREATE TABLE publishes (
    idempotency_key TEXT PRIMARY KEY,   -- ← 去重键
    thread_id, content_hash, output_path, published_at, result_json
)
```

publish 时先查 key 是否存在：存在 → 返回上次结果（no-op）；不存在 → 真执行 + 写表。这个表也是审计日志（`get_publish_history`）。

---

## 3. publish_report：带幂等的副作用工具

```python
def publish_report(thread_id, content, dry_run=None) -> dict:
    key = idempotency_key(thread_id, content)
    if dry_run:
        return {"published": False, "dry_run": True, ...}   # 只打印不执行

    row = 查注册表(key)
    if row 已存在:
        return row.result + {"idempotent_replay": True}     # 幂等 no-op

    # 新发布：写 outputs/ + 注册表
    ...
    return {"published": True, "idempotent_replay": False, ...}
```

### 3.1 dry-run 模式

`publish_dry_run=True` 时只打印将执行的动作不真执行（不写文件、不记注册表）。用途：上线前演练副作用路径，验证「会不会走到 publish、走到时内容对不对」，不留痕迹。

---

## 4. 接进图：可选的 publish 节点

```python
# graph.py（enable_publish 时）
if settings.enable_publish:
    builder.add_node("publish", make_publish_node())
    # reviewer PASS → publish → END（而非直接 END）
    def review_route_with_publish(state):
        target = review_route(state)
        return "publish" if target == END else target
    builder.add_conditional_edges("reviewer", review_route_with_publish)
    builder.add_edge("publish", END)
else:
    builder.add_conditional_edges("reviewer", review_route)  # 现状：pass→END
```

> 🎯 **核心认知**：`enable_publish=False` 时图结构与现状**完全一致**（没有 publish 节点，reviewer pass 直接 END）。这是「默认关 = 零差异」原则的体现——测试 `test_graph_no_publish_node_when_disabled` 断言节点集不含 publish。

---

## 5. 方案对比：怎么治理不可重放副作用？

| 方案 | 做法 | 取舍 |
|---|---|---|
| ① **无护栏** | 裸奔，重复执行就重复执行 | ✅ 零开发；🚫 重复发布 = 生产事故 |
| ② **幂等键**（本课主路线） | hash(thread_id+内容指纹)，已发布的 key 返回 no-op | ✅ 挡重放、有审计日志、轻量（sqlite）；🚫 只能挡「重复」，挡不了「首次但不该执行」（那是 L05 审批的事） |
| ③ **事务 / Saga 补偿** | 分布式事务，失败时跑补偿动作回滚 | ✅ 分布式正统、能回滚；🚫 重（要协调者、要每个动作写补偿），单体 Agent 用不上 |

**选 ② 的理由**：方案 ① 是事故，方案 ③ 杀鸡用牛刀（Agent 是单进程，不是分布式系统）。幂等键 + L05 审批门组合，覆盖了「重放」和「不该执行」两种风险。Saga/事务在「讲概念」时提一句，说什么规模才需要（多服务跨库的分布式事务）。

> 💡 **紧还是松？**（自主-控制主线）：幂等键是「紧」的（永远挡重放），但内容指纹让它「该松时松」（内容变了算新发布，不挡用户想要的更新）。dry-run 是「演练用的松」——验证路径但不留痕。

---

## 6. 跑起来：故障⑥前半 before/after

### `code.py` 演示

```
【before · 裸奔】（无幂等键）
  第 1 次 publish：seq=1  → 真的发布了 ⚠️
  第 2 次 publish：seq=2  → 又发布了一次 ☠️（重复发布事故）
  实际发布次数：2（应该 1 次）

【after · 开幂等键】
  第 1 次 publish：replay=False, seq=1  → 真发布
  第 2 次 publish：replay=True           → 幂等 no-op ✅
  第 3 次 publish（内容变了）：replay=False, seq=2  → 新发布
  发布历史记录数：2（去重后）
```

```bash
cd portfolio-projects/research-assistant
python ../../agent-ops-lessons/04_sideeffect_idempotent/code.py
```

---

## 7. 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/research_assistant/publish.py` | **新增**：`publish_report`（幂等键+sqlite 注册表+dry-run）+ `make_publish_node` | `pytest tests/test_publish.py -q` |
| `src/research_assistant/state.py` | **新增**：`publish_result` 字段 | import 不报错 |
| `src/research_assistant/config.py` | **新增**：`enable_publish`/`publish_dry_run`（默认关） | 改 `.env` |
| `src/research_assistant/graph.py` | `enable_publish` 时加 publish 节点（reviewer PASS→publish→END）；关时现状等价 | 见下 |
| `src/research_assistant/service.py` + `cli.py` | `_initial_state` 加 `publish_result` | 跑 cli 不报错 |
| `tests/test_publish.py` | **新增**：14 个测试（幂等键/重放/dry-run/图结构开关） | `pytest tests/test_publish.py -q` |

### 验收

```bash
cd portfolio-projects/research-assistant

# 1. 全部测试绿（171 + 14 = 185）
python -m pytest -q
# 预期：185 passed

# 2. enable_publish=off 时图与现状等价（节点集不含 publish）
python -m pytest tests/test_publish.py::test_graph_no_publish_node_when_disabled -q
# 预期：passed

# 3. 幂等：同 thread+同内容第二次 no-op
python -c "
from research_assistant import publish
publish._DB_PATH = ':memory:'  # 测试用（实际 sqlite 不支持 memory 建表，用临时文件）
import tempfile, os
publish._DB_PATH = os.path.join(tempfile.mkdtemp(), 't.db')
r1 = publish.publish_report('t1', '内容')
r2 = publish.publish_report('t1', '内容')
print('第1次 replay:', r1['idempotent_replay'], '| 第2次 replay:', r2['idempotent_replay'])
"
# 预期：第1次 replay: False | 第2次 replay: True
```

---

## 8. 本课在两条主线上的位置

- **爆炸半径主线**：把「危险副作用」的爆炸半径从**无界**（重复执行 N 次就发布 N 次）压到**有界**（幂等键让同内容只执行 1 次，内容变了才算新发布）。
- **自主-控制主线**：幂等键是「紧」（永远挡重放），但内容指纹让它「该松时松」（改进版能发布）。幂等只挡「重放」，挡不了「首次但不该执行」——那是 L05 审批门的事。两者叠加才是完整的危险动作治理。

---

## 🎯 面试话术

> 「我给 Agent 的工具做副作用三级分类：只读（search）、可重放（写本地文件）、不可重放（发布/发邮件/下单）。不可重放的动作必须有幂等键——我的 `publish_report` 用 `hash(thread_id + 内容指纹)` 做键，已发布的键直接返回上次结果（no-op）。
>
> 为什么用内容指纹而不只是 thread_id：reviewer 打回重写后的改进版，内容变了就该算新发布；只有内容完全相同才算重复。这个判断让幂等键『该紧时紧（挡重放）、该松时松（放改进版）』。
>
> 我的 Agent 重跑、打回重写、断点恢复都可能重放路径——幂等是敢自动化的前提。L06 断点续跑不重放副作用，就建立在这个幂等键上：崩溃恢复时已 publish 的键不会再执行。
>
> 幂等只挡重放，挡不了『首次但不该执行』——那是下一课 L05 人在环审批门的事。两者叠加才是完整的危险动作治理。」
