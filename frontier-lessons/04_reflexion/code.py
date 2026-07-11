"""L04 · Reflexion 手写：让失败变成语言化的教训。

零框架手写最小 Reflexion loop：
    Actor（执行）→ Evaluator（判成败）→ Self-Reflect（生成反思）→ 带反思重试

对比实验：
    ① 盲目重试（无反思）：重试 N 轮，每轮都犯同样的错
    ② 带反思重试：第 1 轮错→反思→第 2 轮改对

用 Mock LLM 保证可跑（不依赖真实 API），但诚实标注：
    mock 预设了"反思后答对"的行为，成功率对比是演示性的。
    真实 LLM 的反思质量取决于模型能力——反思可能空泛（行为不变，成功率不升）。

跑法：
    cd frontier-lessons/04_reflexion
    python code.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ════════════════════════════════════════════════════════════
# 数据结构
# ════════════════════════════════════════════════════════════
@dataclass
class TraceStep:
    """一轮执行的轨迹记录。"""
    round: int
    action: str        # Actor 做了什么（如搜索词）
    result: str        # 执行结果
    success: bool      # 是否成功
    reflection: str = ""  # 本轮失败后的反思（成功时为空）


@dataclass
class ReflexionResult:
    """Reflexion loop 的最终结果。"""
    success: bool
    rounds: int
    trace: list[TraceStep] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)


# ════════════════════════════════════════════════════════════
# Mock 组件：模拟 Actor / Evaluator / Reflector
# ════════════════════════════════════════════════════════════

class MockActor:
    """模拟 Actor：根据是否有反思改变行为。

    无反思时：用宽泛搜索词，结果"太宽泛"（失败）。
    有反思时：按反思建议改搜索词，结果"精准"（成功）。

    这模拟了真实 LLM"看到反思后改变行为"的机制。
    """

    def __init__(self, fail_mode="vague"):
        self.fail_mode = fail_mode
        self.call_count = 0

    def act(self, task: str, reflections: list[str]) -> tuple[str, str]:
        """执行任务，返回 (action, result)。"""
        self.call_count += 1

        if not reflections:
            # 无反思：用宽泛搜索词
            action = f"搜索 '{task}'"
            result = f"返回大量泛泛的结果，未命中关键信息（搜索词太宽泛）"
            return action, result

        # 有反思：按反思建议改
        # 解析反思里的搜索词建议（mock：反思含"加年份"就加年份）
        if any("年份" in r for r in reflections):
            action = f"搜索 '{task} 2024 协议设计'"
            result = f"返回精准结果：找到了 {task} 的核心协议设计文档"
            return action, result
        if any("限定" in r or "具体" in r for r in reflections):
            action = f"搜索 '{task} 具体实现方案'"
            result = f"返回精准结果：找到了 {task} 的实现细节"
            return action, result

        # 反思但没给出可执行建议 → 行为不变
        action = f"搜索 '{task}'"
        result = f"返回大量泛泛的结果，未命中关键信息"
        return action, result


class MockEvaluator:
    """模拟 Evaluator：规则判断结果是否达标。"""

    def evaluate(self, result: str, task: str) -> tuple[bool, str]:
        """返回 (success, reason)。"""
        if "精准" in result or "找到了" in result:
            return True, "命中关键信息"
        return False, "结果太宽泛，未命中关键信息"


class MockReflector:
    """模拟 Self-Reflect：生成语言化反思。

    关键：反思必须是具体可执行的教训，不是空泛检讨。
    """

    def __init__(self, mode="good"):
        """mode: 'good'=具体反思, 'vague'=空泛反思, 'random'=随机文本（消融）"""
        self.mode = mode

    def reflect(self, task: str, result: str, reason: str) -> str:
        if self.mode == "good":
            return f"失败原因：搜索词'{task}'太宽泛。下次加年份限定：'{task} 2024 协议设计'，缩小到协议设计维度。"
        elif self.mode == "vague":
            return "我应该更仔细地搜索，下次注意一点。"
        else:  # random（消融实验用）
            return "苹果香蕉橙子西瓜葡萄。今天的天气不错。"


# ════════════════════════════════════════════════════════════
# Reflexion loop 手写
# ════════════════════════════════════════════════════════════

def reflexion_loop(task: str, actor: MockActor, evaluator: MockEvaluator,
                   reflector: MockReflector, max_rounds: int = 3) -> ReflexionResult:
    """最小 Reflexion 循环。

    流程：Actor → Evaluator →（失败则）Reflect → 存记忆 → 带反思重试
    """
    reflections: list[str] = []  # episodic memory：存反思
    trace: list[TraceStep] = []
    prev_action = ""

    for round_idx in range(1, max_rounds + 1):
        # 1. Actor：带历史反思执行
        action, result = actor.act(task, reflections)

        # 2. Evaluator：判成败
        success, reason = evaluator.evaluate(result, task)

        step = TraceStep(round=round_idx, action=action, result=result,
                         success=success, reflection="")
        trace.append(step)

        if success:
            return ReflexionResult(success=True, rounds=round_idx,
                                   trace=trace, reflections=reflections)

        # 3. Self-Reflect：生成反思
        reflection = reflector.reflect(task, result, reason)
        reflections.append(reflection)
        step.reflection = reflection

        # 4. 检测：反思后行为是否实质变化
        if prev_action and action == prev_action:
            print(f"  ⚠️ 轮 {round_idx}: 反思后行为未变（反思可能无效）")
        prev_action = action

    return ReflexionResult(success=False, rounds=max_rounds,
                           trace=trace, reflections=reflections)


# ════════════════════════════════════════════════════════════
# 反思质量检测
# ════════════════════════════════════════════════════════════

def is_reflection_actionable(reflection: str) -> bool:
    """判断反思是否具体可执行（而非空泛检讨）。

    信号1：包含具体操作词
    信号2：不含纯空泛词
    """
    action_words = ["加", "换", "限定", "用", "改为", "增加", "去掉", "缩小", "扩大"]
    has_action = any(w in reflection for w in action_words)
    vague_words = ["更仔细", "更认真", "更努力", "注意一点", "下次注意"]
    is_vague = any(w in reflection for w in vague_words)
    return has_action and not is_vague


# ════════════════════════════════════════════════════════════
# 对比实验：盲目重试 vs 带反思重试
# ════════════════════════════════════════════════════════════

def run_comparison():
    """对比三种模式：盲目重试 / 好反思 / 空泛反思 / 随机文本（消融）。"""
    task = "MCP 协议设计"
    max_rounds = 3

    print("\n── 对比实验：盲目重试 vs 带反思重试 ──────────────")
    print(f"任务：研究 '{task}'，要求命中关键信息\n")

    # 模式 1：盲目重试（无反思）
    print("【模式1：盲目重试（无反思）】")
    actor1 = MockActor()
    evaluator = MockEvaluator()
    no_reflector = MockReflector(mode="good")
    # 盲目重试 = 不把反思传给 Actor（reflections 始终空）
    result1 = reflexion_loop_blind(task, actor1, evaluator, max_rounds)
    print(f"  结果：{'成功' if result1.success else '失败'}（{result1.rounds} 轮）")
    for s in result1.trace:
        print(f"    轮{s.round}: {s.action} → {'✅' if s.success else '❌'}")

    # 模式 2：带好反思重试
    print("\n【模式2：带好反思重试（具体可执行教训）】")
    actor2 = MockActor()
    good_reflector = MockReflector(mode="good")
    result2 = reflexion_loop(task, actor2, evaluator, good_reflector, max_rounds)
    print(f"  结果：{'成功' if result2.success else '失败'}（{result2.rounds} 轮）")
    for s in result2.trace:
        print(f"    轮{s.round}: {s.action} → {'✅' if s.success else '❌'}")
        if s.reflection:
            actionable = is_reflection_actionable(s.reflection)
            print(f"           反思{'✅(具体)' if actionable else '❌(空泛)'}: {s.reflection[:60]}")

    # 模式 3：带空泛反思重试
    print("\n【模式3：带空泛反思重试（'应该更仔细'）】")
    actor3 = MockActor()
    vague_reflector = MockReflector(mode="vague")
    result3 = reflexion_loop(task, actor3, evaluator, vague_reflector, max_rounds)
    print(f"  结果：{'成功' if result3.success else '失败'}（{result3.rounds} 轮）")
    for s in result3.trace:
        print(f"    轮{s.round}: {s.action} → {'✅' if s.success else '❌'}")
        if s.reflection:
            actionable = is_reflection_actionable(s.reflection)
            print(f"           反思{'✅(具体)' if actionable else '❌(空泛)'}: {s.reflection[:60]}")

    # 模式 4：消融——随机文本代替反思
    print("\n【模式4：消融——随机文本代替反思】")
    actor4 = MockActor()
    random_reflector = MockReflector(mode="random")
    result4 = reflexion_loop(task, actor4, evaluator, random_reflector, max_rounds)
    print(f"  结果：{'成功' if result4.success else '失败'}（{result4.rounds} 轮）")
    print(f"  → 反思是随机文本，Actor 行为不变，和盲目重试一样失败")

    # 总结
    print("\n── 成功率对比 ────────────────────────────────────")
    print(f"  盲目重试：      {'成功' if result1.success else '失败'}")
    print(f"  好反思重试：    {'成功' if result2.success else '失败'}")
    print(f"  空泛反思重试：  {'成功' if result3.success else '失败'}")
    print(f"  随机文本（消融）：{'成功' if result4.success else '失败'}")
    print(f"\n  结论：只有具体可执行的反思才提升成功率。")
    print(f"  空泛反思=盲目重试≈随机文本（消融）——证明起作用的是反思内容。")

    return result1, result2, result3, result4


def reflexion_loop_blind(task: str, actor: MockActor, evaluator: MockEvaluator,
                         max_rounds: int) -> ReflexionResult:
    """盲目重试：不把反思传给 Actor（reflections 始终空）。"""
    trace: list[TraceStep] = []
    for round_idx in range(1, max_rounds + 1):
        action, result = actor.act(task, [])  # 始终空反思
        success, reason = evaluator.evaluate(result, task)
        step = TraceStep(round=round_idx, action=action, result=result, success=success)
        trace.append(step)
        if success:
            return ReflexionResult(success=True, rounds=round_idx, trace=trace)
    return ReflexionResult(success=False, rounds=max_rounds, trace=trace)


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("L04 Reflexion 手写：让失败变成语言化的教训")
    print("=" * 60)

    print("\n── Reflexion 三组件 ─────────────────────────────")
    print("  Actor:        执行任务（搜索/回答）")
    print("  Evaluator:    判断成功/失败")
    print("  Self-Reflect: 生成具体可执行的反思")
    print("  Episodic Mem: 存反思，下次重试注入 prompt")

    # 演示反思质量检测
    print("\n── 反思质量检测 ─────────────────────────────────")
    test_reflections = [
        "搜索词太宽泛，下次加年份限定：'MCP 2024 协议设计'",
        "我应该更仔细地搜索",
        "结果不够好，下次努力",
        "去掉泛泛的关键词，换成具体技术名'MCP JSON-RPC'",
    ]
    for r in test_reflections:
        actionable = is_reflection_actionable(r)
        print(f"  {'✅ 具体' if actionable else '❌ 空泛'}: {r[:50]}")

    # 对比实验
    run_comparison()

    print("\n" + "=" * 60)
    print("✅ Reflexion = 失败→具体反思→注入重试→行为改变→成功")
    print("⚠️  mock 预设了反思后答对，成功率对比是演示性的。")
    print("   真实 LLM 反思质量决定效果——空泛反思=盲目重试。")
    print("=" * 60)


if __name__ == "__main__":
    main()
