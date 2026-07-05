# Lesson 06 — 多模型路由与网络拓扑（LangGraph 段收官）

> **本课定位**：这是 LangGraph 主干段（L01-L06）的**收官课**。做两件事：① 把前 5 课学的拓扑做**系统总览**（星型/网状/层级/流水线）；② 引入**多模型路由**——不同 Agent 用不同模型，在保证质量的前提下大幅降本。这是 Agent L08 没有的概念（全程单一模型）。
>
> **映射的手写课**：`agent-lessons/08_multi_agent`（全程用同一个 `CHAT_MODEL`，没有按角色选模型的意识）。
>
> **收官的前序课**：L01-L05 全部（本课把它们的拓扑归类总览）。

---

## 一、先回顾：你 Agent L08 用了几个模型？

打开 `agent-lessons/08_multi_agent/code.py`：

```python
CHAT_MODEL = "glm-4"  # ← 规划者、执行者、审查者全部用它
```

planner、executor、reviewer 三个 Agent **全用 glm-4**。这有个浪费：

| Agent | 干的活 | 真的需要 glm-4 吗？ |
|---|---|---|
| planner | 拆任务 | **需要**（规划要聪明）|
| executor | 调工具执行 | 不需要（执行简单，glm-4-flash 够）|
| reviewer | 审查质量 | **需要**（判断要准）|

executor 用 glm-4 是浪费——它的活简单，glm-4-flash（免费）就能干。**多模型路由就是解决这个问题**：让每个 Agent 用最适合自己的模型。

---

## 二、第一部分：四种网络拓扑总览

前 5 课学了各种拓扑，本课把它们归类到四种经典网络拓扑：

### ① 星型（Star / Hub-and-Spoke）— L01 Supervisor

```
        ┌──────────┐
        │supervisor│
        └──┬─┬─┬───┘
           │ │ │
     ┌─────┘ │ └─────┐
     ▼       ▼       ▼
  worker   worker  worker
```
- **特点**：中心调度，worker 只跟中心通信
- **本课对应**：L01 `create_supervisor`
- **适合**：流程不可预测，需中心动态决策

### ② 网状（Mesh）— L02 Swarm

```
  ┌────────┐
  │agent A │──┐
  └────┬───┘  │
       │  ┌───▼────┐
       └──│agent B │
          └───┬────┘
              │
          ┌───▼────┐
          │agent C │
          └────────┘
```
- **特点**：Agent 间直接 handoff，无中心
- **本课对应**：L02 `create_swarm`
- **适合**：流程相对固定，Agent 各知下一步（客服）

### ③ 层级（Hierarchy）— L01 + L03 子图

```
      ┌──────────┐
      │ 顶层 supv │
      └──┬───┬───┘
         │   │
    ┌────▼┐ ┌▼────┐
    │子图1│ │子图2│   （内部各有拓扑）
    └─────┘ └─────┘
```
- **特点**：多层调度，大系统分而治之
- **本课对应**：L01 supervisor + L03 子图
- **适合**：Agent 数量多，需分组管理

### ④ 流水线（Pipeline）— L04 并行 / 手写 L08

```
START → A → B → C → END      （串行流水线）
       或
START → split → [worker, worker, worker] → reduce → END  （并行 map-reduce）
```
- **特点**：固定顺序或并行，无动态路由
- **本课对应**：L04 `Send` map-reduce / 手写 L08 的 for 循环
- **适合**：流程确定，步骤明确

### 真实系统是混合拓扑

```
顶层：层级（按部门分）
  ├── 客服部：星型（supervisor 调度）
  │     └── 退款/售后/投诉（worker）
  ├── 研究部：并行 map-reduce（多研究员并行）
  └── 数据部：流水线（ETL 固定步骤）
```

> 💡 **架构师思维**：没有"最好的拓扑"，只有"最适合场景的拓扑"。选型依据：流程是否可预测、Agent 数量、延迟/成本要求。

---

## 三、第二部分：多模型路由（降本核心）

### 为什么要多模型？

| 模型 | 特点 | 适合 | 成本 |
|---|---|---|---|
| glm-4 | 聪明、推理强 | 决策、路由、审查、创作 | 💰 收费 |
| glm-4-flash | 快、够用 | 执行、查资料、简单转换 | 🆓 免费 |

**洞察**：在一个多 Agent 系统里：
- **决策类**（supervisor 路由、reviewer 审查）次数少但关键——用 glm-4
- **执行类**（researcher 查资料、worker 转换）次数多但简单——用 glm-4-flash

这样**决策质量不降，执行成本≈0**。

### 怎么实现？

```python
# 两个 LLM 实例
smart_llm = ChatZhipuAI(model="glm-4", api_key=api_key)        # 决策用
fast_llm = ChatZhipuAI(model="glm-4-flash", api_key=api_key)   # 执行用

# worker 用 fast（执行便宜）
researcher = create_agent(fast_llm, tools=[], name="researcher", ...)

# supervisor 用 smart（决策要准）
supervisor = create_supervisor(
    agents=[researcher, ...],
    model=smart_llm,  # ⭐ 只有 supervisor 用贵的
)
```

就这么简单——**不同 Agent 传不同的 llm 实例**。LangGraph 完全支持同一个图里多个 LLM 实例协作。

### 差异化模型（进阶）

不仅 supervisor 和 worker 可以不同，**不同 worker 也可以用不同模型**：

```python
researcher = create_agent(fast_llm, ...)    # 查资料：速度优先（flash）
writer = create_agent(smart_llm, ...)       # 写文案：质量优先（glm-4）
```

按任务特点选模型：查资料要快（flash），写文案要好（glm-4）。

---

## 四、成本对比（直觉）

假设一个研究任务跑 5 次 LLM：

| 方案 | supervisor | worker×4 | 总成本 |
|---|---|---|---|
| 全 glm-4（前 5 课）| glm-4 ×1 | glm-4 ×4 | 5 × 收费 |
| 多模型路由 | glm-4 ×1 | flash ×4 | 1 × 收费 + 0（执行免费）|

**省了 80% 的收费调用**。而且决策质量不变（supervisor 还是 glm-4）。

> ⚠️ **注意**：glm-4-flash 在复杂推理上不如 glm-4。如果你的 worker 做的是复杂分析（不是简单查资料），可能还是得用 glm-4。多模型路由的前提是"执行类任务 flash 能胜任"。

---

## 五、前 6 课全景回顾（LangGraph 段完成）

| 课 | 核心概念 | 关键 API |
|---|---|---|
| L01 | 星型拓扑（supervisor）| `create_supervisor` |
| L02 | 网状拓扑（swarm + handoff）| `create_swarm` + `create_handoff_tool` |
| L03 | 层级（子图模块化）| `add_node(name, compiled_graph)` |
| L04 | 并行（map-reduce）| `Send` + `operator.add` reducer |
| L05 | 通信（消息/State/黑板）| `Annotated[list, reducer]` |
| **L06** | **多模型路由 + 拓扑总览** | **多 LLM 实例** |

学完这 6 课，你掌握了 LangGraph 多智能体的**全部核心架构能力**：能搭 supervisor/swarm、能模块化（子图）、能并行（map-reduce）、能通信（共享 State/黑板）、能降本（多模型）。

---

## 六、本课代码

`code.py` 三个实验：

1. **实验 1（拓扑总览）**：打印四种拓扑的 ASCII 图 + 对比表，系统回顾前 5 课
2. **实验 2（多模型路由）**：supervisor(glm-4) + worker(glm-4-flash)，消息流标注每个 agent 的模型
3. **实验 3（层级差异化）**：researcher(flash 查资料) + writer(glm-4 写文案)，按任务特点选模型

```bash
python workflow-lessons/06_multimodel_routing/code.py
```

---

## 七、小结 & 下节预告

**✅ 本课要点**：
- 四种拓扑总览：星型(L01)/网状(L02)/层级(L01+L03)/流水线(L04)
- 多模型路由：supervisor 用 glm-4（决策），worker 用 glm-4-flash（执行免费）
- 差异化模型：不同 worker 按任务特点选模型（查资料用快，写作用贵）
- 降本逻辑：决策次数少（贵），执行次数多（免费），整体成本大降
- 真实系统是混合拓扑：顶层层级 + 中层星型 + 底层流水线

**🔜 下节预告（L07 — CrewAI 对比）**：
LangGraph 段（L01-L06）全部完成！接下来进入**横向框架对比**段。L07 用 CrewAI 重写同样的多 Agent 系统，对比两种范式：LangGraph 的「节点+边」命令式图 vs CrewAI 的「角色+任务」声明式编队。看清两种范式的取舍。

> ⚠️ **清醒认知**：多模型路由的前提是你清楚每个模型的"能力边界"。glm-4-flash 在简单任务上够用，但复杂推理会翻车。生产环境建议先测试 fast 模型在你的具体执行任务上是否合格，再决定是否用它。盲目省钱可能导致 worker 输出质量下降——而 supervisor 可能发现不了（它只看结果不看过程）。
