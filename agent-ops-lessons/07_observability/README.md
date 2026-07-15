# Lesson 07 — 轨迹级可观测：一次运行一行体检报告

> 本课目标：**把 L01–L06 治理机制的运行状况变成可看、可比、可告警的指标**。每次运行结束输出一行结构化 run summary（步数/循环刹车/token与预算比/降级次数/熔断开闭/审批等待/恢复次数/结局），超阈值打 WARNING 告警。
>
> 学完你能回答面试官那句：**「你的 Agent 上线后怎么知道它健康？」**——答案是每次运行一行 run summary + 阈值告警；翻日志是事后侦查，run summary 是实时体检，超阈值当场告警，不等用户投诉。

---

## 0. 起点：请求级观测管不了轨迹健康

ops-L01/L02 给 kb-qa 做了请求级观测：trace_id 贯穿一次请求、结构化日志、Langfuse tracing。但这些看的是 **span 级**（单步发生了什么），回答不了「这次跑得健康吗」。

> 🎯 **核心认知**：Agent 的健康问题不在「某一步」，而在「整条轨迹的聚合」——步数是不是太高（疑似卡死）、token 是不是烧太多（超支）、降级是不是太多（检索质量差）、熔断是不是打开了（工具挂了）。这些是**运行级聚合指标**，span 级日志回答不了，要 run summary。

---

## 1. run summary：一次运行一行体检报告

### 1.1 字段设计（对齐 frontier-L08 评估，以便复用分析脚本）

```python
@dataclass
class RunSummary:
    run_id, thread_id, topic
    # ── 步数（L01）──
    total_steps          # 全局步数
    loop_brakes          # 循环检测触发次数
    # ── 成本（L02）──
    total_tokens         # 累计 token
    budget_ratio         # token / max_budget
    cost_mode            # normal/frugal/over_budget
    # ── 降级（L03）──
    degraded_subtopics   # 检索失败子题数
    breaker_tripped      # 熔断器是否打开过
    # ── 副作用（L04/L05）──
    published, publish_replayed, approval_waited, approval_rejected
    # ── 恢复（L06）──
    resumed              # 是否恢复运行
    # ── 结局 ──
    outcome              # completed/truncated/failed/awaiting_approval
    elapsed
    # ── 告警 ──
    alerts               # 阈值触发的告警列表
```

字段刻意对齐 frontier-L08 的 `MetricCard`，这样 L08 的分析脚本能复用——只是语义不同：

| 维度 | frontier-L08（评估） | **L07（观测）** |
|---|---|---|
| 算什么 | 质量指标（任务成功率/步数效率/循环） | 健康指标（步数/成本/降级/熔断） |
| 时机 | 事后、离线、批量 | **实时、在线、单次** |
| 用途 | 比较机制收益（加记忆好多少） | 监控运行健康（这次跑得稳不稳） |

### 1.2 一行格式（日志友好）

```
✅ [completed] run=api-1234 steps=8 tokens=1200(2%) mode=normal degraded=0 breaker=off
published=Y approval=- resumed=N 3.2s
```

```
🟡 [truncated] run=api-5678 steps=30 tokens=47500(95%) mode=over_budget degraded=3 ...
| ⚠️ 步数过高（30）; ⚠️ 预算将耗尽（95%）; ⚠️ 降级子题多（3）
```

---

## 2. 阈值告警：超阈值当场 WARNING

```python
def _check_alerts(s):
    alerts = []
    if s.total_steps >= settings.alert_steps_high:           # 默认 25
        alerts.append("⚠️ 步数过高，疑似卡死或低效")
    if s.budget_ratio >= settings.alert_budget_ratio_high:   # 默认 0.9
        alerts.append("⚠️ 预算将耗尽，超支风险")
    if s.degraded_subtopics >= settings.alert_degraded_high: # 默认 2
        alerts.append("⚠️ 降级子题多，检索质量预警")
    if s.breaker_tripped:
        alerts.append("⚠️ 熔断器打开过，工具持续故障")
    return alerts
```

> 💡 生产上这些 WARNING 接告警系统（Prometheus/PagerDuty），本课落日志。关键区别：**翻日志是事后侦查**（出事了去挖 span），**run summary 告警是实时体检**（跑完就知道这次不健康，不等用户投诉）。

---

## 3. 六类故障 × run summary 对比

```
场景      结局         步数  token   降级  告警
pure    ✅ completed    7    142    0    —
slow    ✅ completed    7    124    1    —       ← L03 兜住（降级声明）
flaky   ✅ completed    7    162    1    —       ← L03 兜住
loop    ✅ completed   11    220    0    —       ← L01 兜住（步数有上限）
crash   ✅ completed    8    115    0    —       ← L06 兜住（续跑）
bomb    ✅ completed    7  70714    0    —       ← L02 触发 over_budget
```

> 🎯 **核心认知**：这张表一眼看出每类故障被哪个机制兜住、代价多少。这就是 run summary 的价值——**可比较**。L08 的混沌收益矩阵正是基于这种 summary 跑批出来的。

---

## 4. 方案对比：怎么观测 Agent 健康？

| 方案 | 做法 | 取舍 |
|---|---|---|
| ① **翻原始日志**（现状） | 出事了 grep trace_id 挖 span | ✅ 细节全；🚫 事后侦查，不告警；轨迹一长就淹没在 span 里 |
| ② **显式 run summary**（本课主路线） | 每次运行结束输出一行聚合 + 阈值告警 | ✅ 实时体检、可比较、超阈值告警；🚫 字段要设计（对齐评估一次性设计好） |
| ③ **全量 APM / Langfuse** | ops-L02 已有 tracing，看 span 树 | ✅ 可视化好；🚫 看的是 span 不是运行级聚合，轨迹健康仍要 run summary 补 |

**选 ② 的理由**：方案 ① 是被动响应（出事再挖），方案 ③ 是 span 级（看单步不是运行）。run summary 是运行级聚合，回答「这次跑得健康吗」，三者互补不替代。

> 💡 **紧还是松？**（自主-控制主线）：告警阈值是「紧松」的核心。`alert_steps_high=25` 太紧正常长任务也告警（狼来了），太松（如 100）卡死了才发现。判断依据是「正常路径的步数 × 安全系数」——和 L01 的 max_total_steps 联动设（告警阈值 < 截断阈值，先告警再截断）。

---

## 5. 跑起来

### `code.py` 演示

```bash
cd portfolio-projects/research-assistant
python ../../agent-ops-lessons/07_observability/code.py
```

演示：
1. **六类故障 × run summary 对比**：六行表格，一眼看出每类故障被哪个机制兜住。
2. **阈值告警**：问题跑触发 3 条告警（步数/预算/降级）。
3. **与 ops 请求级日志的分层**：三层观测互补。

---

## 6. 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/research_assistant/run_summary.py` | **新增**：`RunSummary` + `build_summary` + `_check_alerts` + `format_summary_line` + `emit_summary` | `pytest tests/test_run_summary.py -q` |
| `src/research_assistant/config.py` | **新增**：`enable_run_summary`/`alert_steps_high`/`alert_budget_ratio_high`/`alert_degraded_high`（默认关） | 改 `.env` |
| `src/research_assistant/service.py` | invoke 结束时 `emit_summary`（enable_run_summary 时）；加 `import time` | 见下 |
| `tests/test_run_summary.py` | **新增**：15 个测试（字段提取/阈值告警/六类故障对比） | `pytest tests/test_run_summary.py -q` |

### 验收

```bash
cd portfolio-projects/research-assistant

# 1. 全部测试绿（204 + 15 = 219）
python -m pytest -q
# 预期：219 passed

# 2. 阈值告警触发
python -m pytest tests/test_run_summary.py::test_alert_steps_high -q
# 预期：passed

# 3. 六类故障 summary 对比
python -m pytest tests/test_run_summary.py::test_six_faults_summary_comparison -q
# 预期：passed（bomb 场景 token 最高）

# 4. 开 enable_run_summary 后每次运行出 summary 行（看日志）
python -c "
from research_assistant import config
config.settings.__dict__['enable_run_summary'] = True
from research_assistant.run_summary import build_summary, format_summary_line
s = build_summary({'step_count':8,'token_usage':1200,'failed_subtopics':[],'truncated':False,'publish_result':{},'cost_mode':'normal'}, run_id='demo')
print(format_summary_line(s))
"
# 预期：✅ [completed] run=demo steps=8 tokens=1200...
```

---

## 7. 本课在两条主线上的位置

- **爆炸半径主线**：观测本身不缩小爆炸半径，但它让「半径有没有被兜住」**可见**。没有 run summary，治理机制（L01–L06）的效果是「黑箱」——开了步数预算不知道有没有触发、开了熔断不知道有没有打开。run summary 把这些变成可看的数字。
- **自主-控制主线**：告警阈值的「紧松」判断依据是「正常路径指标 × 安全系数」——太紧正常任务也告警（狼来了），太松出事了才发现。和 L01 的 max_total_steps 联动：告警阈值 < 截断阈值，先告警再截断。

---

## 🎯 面试话术

> 「我的 Agent 每次运行出一行体检报告：步数、token 与预算比、降级次数、熔断状态、审批、恢复、结局分类。翻日志是事后侦查——出事去挖 span；run summary 是实时体检——跑完就知道这次健不健康，超阈值当场打 WARNING 告警，不等用户投诉。
>
> 字段设计对齐了我 frontier 课程的轨迹评估，但语义不同：评估算质量指标（事后离线批量），观测算健康指标（实时在线单次）。这样 L08 的混沌收益矩阵能复用同一套字段做跑批分析。
>
> 三层观测互补：ops 的请求级日志/tracing 看单步细节，run summary 看运行级健康，frontier 的评估看质量。告警阈值的紧松判断依据是『正常路径步数 × 安全系数』，和 L01 的 max_total_steps 联动——告警阈值小于截断阈值，先告警再截断。」
