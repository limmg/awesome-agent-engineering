# Lesson 01 — 步数与循环：给轨迹装里程表

> 本课目标：**把分散的局部限位（max_rewrites / max_re_research / browser_max_steps）统一为全局步数预算，装上运行时循环检测**——让故障③（循环诱导）从「撞 recursion_limit 崩溃」变成「第 N 步诚实收尾，带着已有材料出部分结果」。
>
> 学完你能回答面试官那句：**「你的 Agent 会死循环吗？怎么防？」**——答案是双层：全局步数预算触发诚实收尾，recursion_limit 做最后保险丝，循环用动作签名在线检测。

---

## 0. 起点：L00 基线里故障③的裸奔结局

L00 的 `baseline_chaos.json` 记录了故障③（循环诱导）的结局是 `caught`——**局部限位兜住了**。但诚实记录里写了「步数从 7 涨到 11」。这个「兜住」是有代价的：

```
现状局部限位盘点：
  max_rewrites=3       reviewer→writer 打回循环最多 3 次
  max_re_research=2    事实冲突补研最多 2 次
  browser_max_steps=12 浏览器 agent 最多 12 步
  recursion_limit=25   langgraph 默认（崩溃式，非收尾）
```

> 🎯 **核心认知**：这些限位**正交**——每个回路都在自己的限内，但它们**叠乘**。一次运行的最坏步数上界：

```
最坏步数 ≈ split(1) + researcher×N + summarize(1)
         + [research_team→writer→reviewer] × max_rewrites
         + [research_team→writer→reviewer] × max_re_research
         + reviewer × (max_rewrites + max_re_research)

N=3, max_rewrites=3, max_re_research=2 时：
  ≈ 1 + 3 + 1 + (1+1+1)×3 + (1+1+1)×2 + 5 = 29 步
```

29 步已经**超过** langgraph 默认的 `recursion_limit=25`——意味着最坏情况下局部限位还没用完，recursion_limit 就先崩了。而 recursion_limit 抛的是 `GraphRecursionError`，**不是诚实收尾**——用户看到的是报错，没有部分结果。

---

## 1. 局部限位为什么不够

### 1.1 三类计数器正交，叠乘后总步数仍无界

```
              ┌─── 各自为政的局部限位 ───┐
              │                          │
  max_rewrites=3   max_re_research=2   browser_max_steps=12
       │                  │                    │
       ▼                  ▼                    ▼
   writer 回路        research_team 回路     browser 回路
       │                  │                    │
       └──────────┬───────┴────────────────────┘
                  ▼
          总步数 = 各回路步数之和（无全局约束）
                  │
                  ▼
        可能撞 recursion_limit=25 → GraphRecursionError（崩溃）
```

每个局部限位都在自己的回路里正确地防了死循环，但**没有任何一个约束整条轨迹的总步数**。这是「护请求」思维（ops 课程的局部限流）带到「护轨迹」场景的遗留——请求级限流管的是「单次调用」，轨迹级需要的是「总里程表」。

### 1.2 recursion_limit 是崩溃式收尾，不是诚实收尾

langgraph 的 `recursion_limit` 是图执行的总超级步上限，撞到它抛 `GraphRecursionError`。这有两个问题：

1. **崩溃 = 没有结果**：用户看到 500 错误，前面跑了 24 步的研究材料全丢。
2. **它是最后保险丝，不是业务限位**：用保险丝当业务限位，等于「家里用电靠跳闸来控制」。

> 💡 诚实收尾 vs 崩溃式收尾的本质区别：
> - **诚实收尾**（L01 目标）：超预算时，带着已有材料直接进 writer 出**部分结果**，报告里标注「因步数预算截断」。用户拿到的是「不完整但可用」的报告。
> - **崩溃式收尾**（recursion_limit）：抛异常，用户拿到的是报错。前面所有工作作废。

---

## 2. 全局步数预算：给轨迹装里程表

### 2.1 设计：step_count + add_int reducer

```python
# state.py
def add_int(left, right):
    """整数累加 reducer——并发安全（不怕并行节点写覆盖）。"""
    return (left or 0) + (right or 0)

class SystemState(TypedDict):
    ...
    step_count: Annotated[int, add_int]   # 每个节点返回 1，reducer 累加
    truncated: bool                        # 诚实收尾标志
    action_history: Annotated[list[str], operator.add]  # 动作签名（循环检测用）
```

> 🎯 **核心认知**：`step_count` 用 reducer 而非裸 int，是为了**并发安全**。现状的 `rewrite_count` / `re_research_count` 用裸 int 靠「节点返回全量新值」——一旦未来有并行节点写同一个计数器就会互相覆盖。reducer 让每个节点只报「我走了 1 步」，累加交给 LangGraph。

### 2.2 每个父图节点记账

每个父图节点（research_team / writer / reviewer）在返回值里带上步数增量：

```python
# nodes.py（writer 示例）
from .step_budget import step_delta as _step_delta

def writer(state):
    ...
    return {
        "report": report,
        "messages": [AIMessage(content=report)],
        **_step_delta("writer", summary[:50]),   # ← 记账：step_count += 1
    }
```

`step_delta` 返回 `{"step_count": 1, "action_history": [签名]}`。**开关关闭时也记账**——这样 run summary（L07）能看到步数，但不触发截断判断（现状行为不变）。

### 2.3 诚实收尾：超预算走 writer 而非 raise

在 reviewer 节点的**最前面**检查预算：

```python
# step_budget.py
def should_truncate(state):
    if settings.enable_step_budget:
        if state.get("step_count", 0) >= settings.max_total_steps:
            return True, f"步数预算超限（{step}/{max}）"
    if settings.enable_loop_detect:
        if detect_loop(state.get("action_history", [])):
            return True, "检测到动作循环"
    return False, ""

# nodes.py（reviewer 开头）
truncate, reason = should_truncate(state)
if truncate:
    return {
        "review_decision": "pass",          # ← 强制通过（不 raise）
        "feedback": f"诚实收尾：{reason}",
        **honest_truncation_delta(reason),  # ← truncated=True
        **_step_delta("reviewer", "truncate"),
    }
```

writer 看到 `truncated=True`，在报告开头标注：

```
⚠️ 本次研究因步数预算/循环检测被截断，以下为基于已有材料的部分结果。

【概述】...
【核心要点】...
```

> 🎯 **核心认知**：诚实收尾的关键是「**带着已有材料进 writer**」。reviewer 强制 pass → writer 拿到现有的 research_summary 出部分报告 → 标注截断。用户拿到的是「不完整但诚实」的结果，不是报错。

---

## 3. 运行时循环检测：在线执法

### 3.1 动作签名（复用 frontier-L08 思路，从离线到在线）

frontier-L08 的 `TrajectoryEvaluator` 在**事后**检测循环（跑完看轨迹发现绕路）。L01 把同样的思路搬到**运行时**：

```python
def _signature(node: str, param: str) -> str:
    """节点名 + 关键参数的短哈希。"""
    h = hashlib.md5(param[:80].encode("utf-8")).hexdigest()[:8]
    return f"{node}:{h}"

def detect_loop(action_history, window=3):
    """最近 window 个签名是否全相同（原地打转）。"""
    if len(action_history) < window:
        return False
    return len(set(action_history[-window:])) == 1
```

每次节点执行，签名追加进 `action_history`（reducer 累加）。reviewer 检查时，若末尾 3 个签名相同 → 判定循环 → 触发诚实收尾。

### 3.2 离线检测 vs 在线执法

| 维度 | frontier-L08（离线评估） | **L01（在线执法）** |
|---|---|---|
| 时机 | 跑完之后 | 运行中 |
| 作用 | 发现绕路（改进 prompt/拓扑） | 当场刹车（防跑飞） |
| 代价 | 零（只读轨迹） | 每次 reviewer 多一次滑窗检查 |
| 签名 | 节点+输出文本相似度 | 节点+参数哈希 |

两者互补：在线执法挡住正在发生的循环，离线评估发现「为什么会循环」的根因（供 prompt 优化）。

---

## 4. 方案对比：怎么给循环体装限位？

| 方案 | 做法 | 取舍 |
|---|---|---|
| ① **只靠 recursion_limit** | 设 `recursion_limit=25`，撞到就崩 | ✅ 零开发；🚫 崩溃式（GraphRecursionError，无部分结果）；是保险丝不是业务限位 |
| ② **全局步数预算**（本课主路线） | `step_count` 累计 + 超限诚实收尾（带部分结果退出） | ✅ 细粒度（可配 max_total_steps）、诚实（部分结果 + 截断标注）、并发安全（reducer）；🚫 需要每节点记账（几行） |
| ③ **语义级循环检测** | 让 LLM 判断「是否原地踏步」 | ✅ 能发现签名检测漏的语义重复；🚫 贵（每次多一次 LLM 调用）、慢、不确定 |

**选 ② 的理由**：方案 ① 把保险丝当业务限位，方案 ③ 太贵太慢。步数预算 + 动作签名是性价比最优的——确定性、零额外 LLM 成本、能收尾。语义检测作为可选实验（留给 exercise）。

> 💡 **紧还是松？**（自主-控制主线）：`max_total_steps` 设多少？判断依据是「最坏成功路径的步数 × 安全系数」。现状最坏成功路径 ≈ 10 步（无补研无打回），加余量设 30。太紧（如 8）会误杀正常的长任务；太松（如 100）等于没设。recursion_limit 应设得比 max_total_steps 大（如 40），让它永远是「最后保险丝」而非「常用断路器」。

---

## 5. 跑起来：故障③ before/after

### `code.py` 演示

```
场景                               结局                步数  截断  标注
before（裸奔）                     🟡 local_limit_stop    9    否    否
after（开步数预算 max=8）            ✅ honest_truncate     9    是    是
after（开循环检测 window=3）         🟡 local_limit_stop    9    否    否
after（步数预算 + 循环检测都开）      ✅ honest_truncate     9    是    是
```

**解读**：

- **before**：循环诱导下，局部 `max_rewrites=3` 兜住了（9 步停）。但这是「刚好兜住」——叠加补研（+6 步）或更多子题就会超 recursion_limit 崩。
- **after（步数预算）**：第 8 步预算用完，第 9 步 reviewer 触发诚实收尾，报告带「⚠️ 因步数预算截断」标注。用户拿到部分结果，不是报错。
- **after（循环检测）**：本场景下 reviewer 的签名没有连续重复 3 次（research_team/writer/reviewer 交替），所以循环检测没触发——这说明**签名检测适合「同节点连续重复」的循环**（如 browser 反复点同一个按钮），步数预算才是「总闸」。
- **两个都开**：步数预算先触发（互补，不冲突）。

```bash
cd portfolio-projects/research-assistant
python ../../agent-ops-lessons/01_step_budget/code.py
```

---

## 6. 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/research_assistant/state.py` | **新增**：`add_int` reducer + `step_count`/`truncated`/`action_history` 字段 | `python -c "from research_assistant.state import SystemState; print('ok')"` |
| `src/research_assistant/step_budget.py` | **新增**：`step_delta` / `detect_loop` / `should_truncate` / `honest_truncation_delta` | `python -c "from research_assistant.step_budget import should_truncate; print(should_truncate({'step_count':0}))"` |
| `src/research_assistant/nodes.py` | research_team/writer/reviewer 加 `_step_delta` 记账；reviewer 开头加 `should_truncate` 诚实收尾；writer 加截断标注 | 见下 |
| `src/research_assistant/config.py` | **新增**：`enable_step_budget`/`max_total_steps`/`enable_loop_detect`/`loop_detect_window`（默认全关） | 改 `.env` 设 `ENABLE_STEP_BUDGET=true` |
| `src/research_assistant/service.py` + `cli.py` | `_initial_state` 加新字段（顺便补齐 cli.py 缺失的 L05 字段） | 跑 cli 不报 KeyError |
| `tests/test_step_budget.py` | **新增**：16 个测试（记账/循环检测/诚实收尾/开关行为） | `pytest tests/test_step_budget.py -q` |

### 验收

```bash
cd portfolio-projects/research-assistant

# 1. 全部测试绿（123 现有 + 16 新增 = 139）
python -m pytest -q
# 预期：139 passed

# 2. 开关关时行为 = 现状（核心不变式）
python -m pytest tests/test_graph.py tests/test_nodes.py -q
# 预期：全绿（开关默认关，不触发截断）

# 3. 开步数预算后诚实收尾
python -c "
from research_assistant import config
config.settings.__dict__['enable_step_budget'] = True
config.settings.__dict__['max_total_steps'] = 3
from research_assistant.step_budget import should_truncate
t, r = should_truncate({'step_count': 5, 'action_history': []})
print(t, r)
"
# 预期：True 步数预算超限（5/3）
```

---

## 7. 本课在两条主线上的位置

- **爆炸半径主线**：把「死循环」的爆炸半径从**无界**（撞 recursion_limit 才崩，或局部限位叠乘后仍很大）压到**有界**（max_total_steps 步内必收尾，且带部分结果）。
- **自主-控制主线**：这道闸的「紧松」判断依据是「最坏成功路径步数 × 安全系数」——太紧误杀长任务，太松等于没设。recursion_limit 永远比 max_total_steps 大，只做最后保险丝。

---

## 🎯 面试话术

> 「我的 Agent 防死循环有两层：全局步数预算触发**诚实收尾**——超 max_total_steps 时带着已有材料进 writer 出部分结果、标注截断，而不是 raise 崩掉；recursion_limit 做**最后保险丝**，设得比业务预算大，永远不该靠它兜底。
>
> 循环用动作签名在线检测——节点名加参数哈希，连续重复 3 次判原地打转。这个思路复用了我 frontier 课程的轨迹评估，但从『事后发现绕路』变成了『运行时当场刹车』。
>
> 为什么不用裸 int 计数器？因为 step_count 用了 reducer——现状的 rewrite_count 用裸 int 靠节点返回全量新值，一旦未来有并行节点写同一个计数器就会互相覆盖。reducer 让每个节点只报『我走了 1 步』，累加交给 LangGraph，并发安全。」
