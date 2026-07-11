# Lesson 04 — Reflexion 手写：让失败变成语言化的教训

> 本课目标：**零框架手写最小 Reflexion 循环（执行→自评→语言化反思→带着反思重试），理解它为什么被称为「不用梯度的强化学习」，并对比「盲目重试 vs 带反思重试」的成功率差异。**

学完你能回答：**「Agent 怎么自我修正？Reflexion 是什么？」**——手写过 loop，知道核心不是"让模型检讨"，是把失败转成具体可执行的教训注入重试。

---

## 0. 起点：L00 读过的论文进方法细节

L00 三遍读法带读了 Reflexion 的摘要（"语言化反思能替代梯度更新提升成功率"）。本课进**方法细节**：三组件怎么协作、反思应该长什么样、最常见失败模式怎么检测。

> **论文**：Reflexion: Language Agents with Verbal Reinforcement Learning（Shinn et al. 2023, [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)）

---

## 1. Reflexion 三组件

```
         ┌─────────── Reflexion 循环 ───────────┐
         │                                       │
    ┌────▼─────┐    ┌───────────┐    ┌──────────▼───┐
    │  Actor   │───▶│ Evaluator │───▶│ Self-Reflect │
    │ 执行任务 │    │ 判成败    │    │ 生成反思     │
    └────▲─────┘    └───────────┘    └──────────┬───┘
         │                                       │
         │          ┌───────────────┐            │
         └──────────│  Episodic     │◀───────────┘
           带反思   │  Memory       │  存反思
           重试     │  （存反思）   │
                    └───────────────┘
```

| 组件 | 作用 | 本课实现 |
|---|---|---|
| **Actor** | 执行任务（ReAct loop 或直接调 LLM） | `actor(task, reflection)` |
| **Evaluator** | 判断成功/失败（规则 or LLM judge） | `evaluate(result, expected)` |
| **Self-Reflect** | 生成语言化反思（"为什么失败，下次怎么改"） | `reflect(task, result, trace)` |

### 关键洞察：反思必须是具体的教训

```
✅ 好的反思（具体可执行）：
   "搜索词'MCP'太宽泛，返回了大量无关结果。下次加年份限定：'MCP 2024 协议'"

🚫 坏的反思（空泛检讨）：
   "我应该更仔细地搜索"
   "结果不够好，下次努力"
```

> 🎯 **核心认知**：Reflexion 起作用的不是"多了一轮"这个动作，是**反思内容被注入重试 prompt 后改变了行为**。论文消融实验：把反思换成随机文本，成功率立刻回落——证明起作用的是反思的语义内容，不是轮数。

### 为什么叫"不用梯度的强化学习"

传统 RL：失败 → 更新参数（梯度下降）→ 下次行为改变。
Reflexion：失败 → 生成反思文本 → 注入 prompt → 下次行为改变。

两者都是"从失败学习"，但 Reflexion 用**语言反馈**代替**参数更新**——不需要训练、不需要梯度、不需要 GPU。代价是：反思存在上下文窗口里（有限的），且每次重试都要带上（token 成本）。

---

## 2. 流派对比

**问题**：Agent 失败后怎么修正？

| 流派 | 做法 | 取舍 |
|---|---|---|
| ① 单次 self-critique | 让 LLM 自评一遍改一版就停 | ✅ 便宜；🚫 只改一次，深度不够，不积累教训 |
| ② Reflexion 多轮带记忆重试（本课选它） | 失败→反思→存记忆→带反思重试→再反思 | ✅ 积累教训、成功率随轮次上升；🚫 多轮成本高 |
| ③ 多 Agent 辩论 | 多个 Agent 互相挑刺达成共识 | ✅ 多视角；🚫 成本最高、可能不收敛 |

**选 ② 的理由**：研究助手场景下，失败通常是"搜索词不好""漏了关键维度"这类可改进的错，反思能给出具体修正方向。多 Agent 辩论太重（每次研究要跑多个 Agent），单次 critique 太浅（研究任务可能要多轮才对）。Reflexion 的"积累教训"特性和 L01 的记忆系统天然配合——反思存进 episodic memory，下次类似任务也能用。

### 最常见失败模式：反思了但行为没变

```
失败 → 反思"应该更仔细" → 重试 → 还是同样的错（因为"更仔细"不是可执行指令）
```

**检测方法**：对比连续两轮的 Actor 行为（搜索词/工具调用/输出）是否实质变化。如果反思后行为没变，说明反思是空泛的，需要重新生成更具体的反思。本课 code.py 演示这个检测。

---

## 3. 手写最小 Reflexion loop

### code.py 结构

```python
def reflexion_loop(task, max_rounds=3):
    reflections = []  # episodic memory: 存反思
    for round in range(max_rounds):
        # 1. Actor：带历史反思执行任务
        result = actor(task, reflections)
        # 2. Evaluator：判成败
        success, reason = evaluate(result, task)
        if success:
            return result  # 成功，结束
        # 3. Self-Reflect：生成具体反思
        reflection = reflect(task, result, reason)
        reflections.append(reflection)
        # 4. 检测：反思后行为是否实质变化
        if not behavior_changed(result, prev_result):
            warn("反思无效：行为未改变")
    return result  # 超过轮数，返回最后一次
```

### Mock LLM 设计

为了不依赖真实 API，code.py 用 Mock LLM 演示：
- Actor mock：第一轮答错（模拟"搜索词太宽泛"），第二轮带反思后答对
- Evaluator：规则判断（答案含特定关键词=对）
- Reflector：预设反思文本（"加年份限定"）

### 对比实验

```
盲目重试（无反思）：重试 3 轮，每轮都犯同样的错 → 成功率低
带反思重试：第 1 轮错→反思→第 2 轮改对 → 成功率高
```

> ⚠️ **诚实标注**：code.py 用 mock 预设了"反思后答对"的行为，所以成功率对比是**演示性的**（mock 保证了结果）。真实 LLM 的反思质量取决于模型能力——反思可能是空泛的（此时行为不变，成功率不升）。L05 接入真实 research-assistant 时才能看到真实效果。

---

## 4. 反思的"具体性"检测

本课引入一个重要概念：**反思质量检测**。

```python
def is_reflection_actionable(reflection):
    """判断反思是否具体可执行（而非空泛检讨）。"""
    # 信号1：包含具体操作词（"加""换""限定""用"）
    action_words = ["加", "换", "限定", "用", "改为", "增加", "去掉"]
    has_action = any(w in reflection for w in action_words)
    # 信号2：不是纯空泛词
    vague_words = ["更仔细", "更认真", "更努力", "注意一点"]
    is_vague = any(w in reflection for w in vague_words)
    return has_action and not is_vague
```

这个检测在 L08 的轨迹评估里会作为一个指标——"反思质量"。

---

## 5. 落地清单

本课是**纯手写原理课，无落地改动**（不改 research-assistant 任何文件）。落地在 L05（反思接入研究回路）。

### 如何验证

```bash
cd frontier-lessons/04_reflexion
PYTHONIOENCODING=utf-8 ../../.venv/Scripts/python.exe code.py
# 预期：
# - 演示 Reflexion 三组件循环
# - 对比"盲目重试 vs 带反思重试"成功率
# - 展示一个"反思无效"反例及检测
```

---

## 6. 本课在两条主线上的位置

- **评估主线**：本课引入了"反思质量检测"（反思是否具体可执行）和"行为变化检测"（反思后行为是否实质改变）两个概念。这两个在 L08 的 TrajectoryEvaluator 里会成为正式指标——评估 Agent 的"反思有效性"不只是"有没有反思"。
- **上下文工程主线**：Reflexion 是上下文工程的**动态组装**——反思存进 episodic memory，重试时从 memory 调回注入 prompt。这和 L01 的记忆系统无缝衔接：反思就是一种特殊的情景记忆。Reflexion 的上下文管理挑战是"反思越积越多会撑爆窗口"——需要控制 max_rounds 和反思长度。

---

## 🎯 面试话术

> 「Reflexion 我手写过 loop：三组件——Actor 执行、Evaluator 判成败、Self-Reflect 生成反思。核心不是"让模型检讨"，是把失败转成具体可执行的教训注入重试。论文消融实验证明起作用的是反思内容不是轮数——把反思换成随机文本成功率就回落。我还知道它最常见的失败模式——反思了但行为没变——以及怎么检测：对比连续两轮的行为是否实质变化。这就是"不用梯度的强化学习"，用语言反馈代替参数更新。」
