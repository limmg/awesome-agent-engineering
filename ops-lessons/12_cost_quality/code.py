"""
Lesson 12 — 成本/质量权衡：把模型选型变成数据
==============================================
本脚本【零外部依赖】演示「同 golden set 两模型对比」的完整决策流程：
    ① glm-4 vs glm-4-flash 在四指标上的质量对比
    ② 成本对比（flash 免费 vs glm-4 按 token 计费）
    ③ context 指标作为对照组（与生成模型无关，应基本相同）
    ④ 决策结论：哪个环节用哪个模型

用 mock 的评估数据演示（真实数据由 run_cost_eval.py 跑 ragas 产出）。
核心是看清「质量-成本权衡怎么变成可读的决策表」。

运行：python code.py
依赖：仅标准库
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# 1. mock 评估数据（模拟真实 ragas 跑出来的四指标 + token）
# ════════════════════════════════════════════════════════════════
# 这些数字模拟「20 题 golden set 分别用 glm-4 / flash 生成」的 ragas 结果。
# 设计意图：
#   - faithfulness：glm-4 明显高（flash 更爱撒谎）→ 生成该用 glm-4
#   - answer_relevancy：glm-4 略高
#   - context_precision/recall：两模型几乎相同（对照组——检索不变，与生成模型无关）
MOCK_RESULTS = {
    "glm-4": {
        "metrics": {
            "faithfulness": 0.86,
            "answer_relevancy": 0.88,
            "context_precision": 0.82,
            "context_recall": 0.79,
        },
        "avg_tokens": {"input": 820, "output": 210},  # 每题平均 token
    },
    "glm-4-flash": {
        "metrics": {
            "faithfulness": 0.61,   # 明显掉（爱撒谎）
            "answer_relevancy": 0.79,
            "context_precision": 0.82,  # 对照组：几乎不变
            "context_recall": 0.79,
        },
        "avg_tokens": {"input": 820, "output": 195},
    },
}

# 价目表（元/百万 token），与 tracing.py 一致
PRICE = {
    "glm-4":       {"input": 50.0, "output": 50.0},
    "glm-4-flash": {"input": 0.0,  "output": 0.0},
}


def cost_per_question(model: str, tokens: dict) -> float:
    """单题成本 = (in×输入价 + out×输出价) / 1e6。"""
    p = PRICE[model]
    return (tokens["input"] * p["input"] + tokens["output"] * p["output"]) / 1_000_000


# ════════════════════════════════════════════════════════════════
# 2. 决策逻辑
# ════════════════════════════════════════════════════════════════
GENERATION_METRICS = ["faithfulness", "answer_relevancy"]  # 生成质量指标
CONTEXT_METRICS = ["context_precision", "context_recall"]   # 检索指标（对照组）


def decide(results: dict) -> dict:
    """对比两模型，产出决策结论。"""
    g4 = results["glm-4"]["metrics"]
    fl = results["glm-4-flash"]["metrics"]

    # 生成质量差（faithfulness 最关键：防幻觉）
    faith_gap = g4["faithfulness"] - fl["faithfulness"]
    rel_gap = g4["answer_relevancy"] - fl["answer_relevancy"]

    # 对照组：context 指标差应≈0（验证实验有效性）
    ctx_gap = max(abs(g4[m] - fl[m]) for m in CONTEXT_METRICS)

    # 决策
    if faith_gap > 0.15:
        gen_choice = "glm-4"
        gen_reason = f"faithfulness 差 {faith_gap:.2f}（flash 明显更爱撒谎，生成不能省）"
    else:
        gen_choice = "glm-4-flash"
        gen_reason = f"faithfulness 差仅 {faith_gap:.2f}（flash 够用，省钱）"

    return {
        "faithfulness_gap": round(faith_gap, 3),
        "relevancy_gap": round(rel_gap, 3),
        "context_gap_max": round(ctx_gap, 3),  # 对照组差，应≈0
        "generation_model": gen_choice,
        "generation_reason": gen_reason,
        "aux_model": "glm-4-flash",  # 改写/judge 辅助环节
        "aux_reason": "质量要求低 + 免费，辅助环节用 flash 最优",
    }


# ════════════════════════════════════════════════════════════════
# 3. main：对比表 + 决策
# ════════════════════════════════════════════════════════════════
def main() -> None:
    N_QUESTIONS = 20

    print("=" * 70)
    print(f"模型选型对比：glm-4 vs glm-4-flash（{N_QUESTIONS} 题 golden set）")
    print("=" * 70)

    # 质量对比表
    print(f"\n{'指标':<22} {'glm-4':<10} {'glm-4-flash':<12} {'差值':<8} 说明")
    print("-" * 70)
    for m in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        g4v = MOCK_RESULTS["glm-4"]["metrics"][m]
        flv = MOCK_RESULTS["glm-4-flash"]["metrics"][m]
        gap = round(g4v - flv, 3)
        tag = "生成质量" if m in GENERATION_METRICS else "对照组(检索)"
        print(f"{m:<22} {g4v:<10} {flv:<12} {gap:<+8} {tag}")

    # 成本对比
    print("\n" + "-" * 70)
    print("成本对比（每题）：")
    for model in ["glm-4", "glm-4-flash"]:
        toks = MOCK_RESULTS[model]["avg_tokens"]
        c = cost_per_question(model, toks)
        total = c * N_QUESTIONS
        print(f"  {model:<14} in={toks['input']} out={toks['output']} → "
              f"¥{c:.5f}/题 × {N_QUESTIONS} = ¥{total:.3f}")

    # 决策
    d = decide(MOCK_RESULTS)
    print("\n" + "=" * 70)
    print("📊 决策结论：")
    print("=" * 70)
    print(f"  对照组检验：context 指标最大差 {d['context_gap_max']}"
          f"（{'✅ ≈0 实验有效' if d['context_gap_max'] < 0.05 else '⚠️ 偏大，检查实验'}）")
    print(f"  生成环节 → {d['generation_model']}")
    print(f"    理由：{d['generation_reason']}")
    print(f"  改写/judge → {d['aux_model']}")
    print(f"    理由：{d['aux_reason']}")

    print("\n💡 总结：质量-成本-延迟三角没有全优解，工程价值在『按环节选模型』。")
    print("   生成留给 glm-4（质量核心），辅助交给 flash（免费够用）——")
    print("   这就是 kb-qa 现有的 answer_model=glm-4 / rewrite_model=flash 配置的数据依据。")


if __name__ == "__main__":
    main()
