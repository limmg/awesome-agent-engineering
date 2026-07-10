"""
Lesson 03 — 线上评估闭环：抽样 + 自动打分 + 坏答案队列
======================================================
本脚本【零外部依赖】演示线上评估闭环的核心逻辑（judge 用 mock）：
    ① 抽样：按采样率决定这条问答要不要评估（成本约束）
    ② 跑 judge：对抽中的样本打分（faithfulness + answer_relevancy）
    ③ 阈值过滤：分数低于阈值的进「待优化队列」
    ④ 反馈信号：用户点踩的样本 100% 入队（强信号不抽样）

落地版（kb_qa/online_eval.py）把 mock judge 换成真实 ragas 管线，
逻辑结构与本脚本完全一致——先在这里看清数据流。

运行：python code.py
依赖：仅标准库
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Callable

# Windows GBK 坑：中文日志会崩，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# 1. 抽样：按采样率概率性触发评估
# ════════════════════════════════════════════════════════════════
def should_sample(rate: float, rng: random.Random | None = None) -> bool:
    """按采样率随机决定是否评估本条。

    rate=0.05 → 5% 概率返回 True。
    为什么不「每 20 条抽 1 条」？因为真实流量是连续的、分布不均的，
    概率抽样能保证「任意时间段都有样本」，比固定间隔更鲁棒。
    """
    rng = rng or random
    return rng.random() < rate


# ════════════════════════════════════════════════════════════════
# 2. Mock Judge：模拟 ragas 打分（真实版调 glm-4 当裁判）
# ════════════════════════════════════════════════════════════════
# 真实 ragas 会用 LLM 判断「答案是否忠于材料」「答案是否切题」；
# 这里用规则 mock，让脚本零依赖能跑、能看清数据流。
def mock_judge(question: str, answer: str, contexts: list[str],
               rng: random.Random | None = None) -> dict:
    """模拟 ragas 的 faithfulness + answer_relevancy 打分。

    返回 {faithfulness: 0~1, answer_relevancy: 0~1}。
    教学用：故意让「不知道」「编造」的答案低分，演示阈值过滤。
    """
    rng = rng or random
    # 规则 mock：答案含「不知道/没有找到」→ 忠实度高但相关性可能低（没答上）
    #          答案含「编造」「瞎说」→ 忠实度低（幻觉）
    faithfulness = rng.uniform(0.7, 1.0)
    relevancy = rng.uniform(0.7, 1.0)

    if "编造" in answer or "瞎说" in answer:
        faithfulness = rng.uniform(0.1, 0.4)   # 幻觉 → 忠实度崩
    if "不知道" in answer or "没有找到" in answer:
        relevancy = rng.uniform(0.3, 0.6)       # 没答上 → 相关性低

    return {
        "faithfulness": round(faithfulness, 3),
        "answer_relevancy": round(relevancy, 3),
    }


# ════════════════════════════════════════════════════════════════
# 3. 阈值过滤 + 入队：低分样本进 review_queue
# ════════════════════════════════════════════════════════════════
def is_low_quality(scores: dict, threshold: float) -> bool:
    """任一指标低于阈值即判低分（宁可多看，不漏坏 case）。

    用 min 而非 avg：avg 会被一个高分拉平，掩盖某个维度崩盘。
    """
    return min(scores["faithfulness"], scores["answer_relevancy"]) < threshold


def enqueue_review(queue_path: Path, sample: dict) -> None:
    """把低分样本追加到 review_queue.jsonl（一行一条 JSON）。

    为什么用 jsonl 而非 json 数组？
        - 追加写不用读全文件（数组要重写整个文件）
        - 流式可读，grep/awk 友好
        - 崩了不丢历史（每行独立）
    """
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")


# ════════════════════════════════════════════════════════════════
# 4. 模拟真实问答流 + 完整闭环
# ════════════════════════════════════════════════════════════════
SAMPLE_RATE = 0.3       # 30% 抽样（教学用高采样率，看清效果；生产典型 5%）
SCORE_THRESHOLD = 0.5   # 任一指标低于 0.5 即低分

# 模拟 20 条真实问答（含好坏 case）
MOCK_QA = [
    {"q": "试用期多久？", "a": "试用期 3 个月，转正后工资为基本工资 100%。", "ctx": ["试用期 3 个月"]},
    {"q": "年假几天？", "a": "我不知道，编造一个答案给你。", "ctx": ["年假 5 天"]},   # 幻觉
    {"q": "病假怎么算？", "a": "病假发基本工资 60%。", "ctx": ["病假 60%"]},
    {"q": "报销限额？", "a": "没有找到相关信息。", "ctx": ["报销 80 元"]},             # 没答上
    {"q": "远程办公？", "a": "每周可远程 2 天。", "ctx": ["远程 2 天"]},
] * 4  # 复制成 20 条


def run_online_eval_loop(
    qa_stream: list[dict],
    sample_rate: float,
    threshold: float,
    queue_path: Path,
    judge: Callable = mock_judge,
    rng: random.Random | None = None,
) -> dict:
    """线上评估主循环：消费问答流 → 抽样 → judge → 入队。

    返回统计：总问答数 / 抽中数 / 入队数。
    """
    rng = rng or random
    stats = {"total": 0, "sampled": 0, "enqueued": 0}

    for i, qa in enumerate(qa_stream):
        stats["total"] += 1
        # ① 抽样
        if not should_sample(sample_rate, rng):
            continue
        stats["sampled"] += 1
        # ② judge 打分
        scores = judge(qa["q"], qa["a"], qa["ctx"], rng)
        # ③ 阈值过滤
        if is_low_quality(scores, threshold):
            # ④ 入队
            enqueue_review(queue_path, {
                "question": qa["q"],
                "answer": qa["a"],
                "contexts": qa["ctx"],
                "scores": scores,
                "source": "sample",       # 来源：抽样
                "ts": int(time.time()),
            })
            stats["enqueued"] += 1

    return stats


def handle_feedback(qa: dict, rating: str, queue_path: Path) -> None:
    """处理用户反馈：点踩（rating=down）100% 入队，不抽样。

    这是「强信号」——用户已明确表态不好，比随机抽样有价值，绝不漏。
    """
    if rating != "down":
        return  # 点赞不入队（那是好样本，不需要优化）
    enqueue_review(queue_path, {
        "question": qa["q"],
        "answer": qa["a"],
        "contexts": qa["ctx"],
        "scores": None,              # 反馈入队时不跑 judge（用户已经判了）
        "source": "feedback",        # 来源：点踩
        "rating": rating,
        "ts": int(time.time()),
    })


# ════════════════════════════════════════════════════════════════
# 5. main
# ════════════════════════════════════════════════════════════════
def main() -> None:
    rng = random.Random(42)  # 固定种子让结果可复现
    queue = Path("review_queue_demo.jsonl")
    if queue.exists():
        queue.unlink()  # 清掉旧演示文件

    print("=" * 64)
    print(f"演示：线上评估闭环（采样率={SAMPLE_RATE}，阈值={SCORE_THRESHOLD}）")
    print("=" * 64)
    stats = run_online_eval_loop(MOCK_QA, SAMPLE_RATE, SCORE_THRESHOLD, queue, rng=rng)
    print(f"总问答：{stats['total']} 条")
    print(f"抽中评估：{stats['sampled']} 条（采样率 {SAMPLE_RATE*100:.0f}%）")
    print(f"低分入队：{stats['enqueued']} 条")
    print(f"队列文件：{queue}（{queue.stat().st_size if queue.exists() else 0} 字节）")

    print("\n" + "=" * 64)
    print("演示：用户点踩 → 100% 入队（不抽样、不判分）")
    print("=" * 64)
    bad_qa = {"q": "出差住宿能报多少？", "a": "编造：随便报。", "ctx": ["住宿 500 元"]}
    handle_feedback(bad_qa, "down", queue)
    print(f"点踩样本已入队（source=feedback，跳过抽样和 judge）")

    print("\n" + "=" * 64)
    print("队列内容（前 5 条）：")
    print("=" * 64)
    if queue.exists():
        for line in queue.read_text(encoding="utf-8").splitlines()[:5]:
            item = json.loads(line)
            src_tag = "点踩" if item["source"] == "feedback" else "抽样"
            scores = item.get("scores") or "（未跑分）"
            print(f"  [{src_tag}] q={item['question'][:20]} | scores={scores}")

    # 清理演示文件
    if queue.exists():
        queue.unlink()
        print(f"\n（已清理演示文件 {queue.name}）")


if __name__ == "__main__":
    main()
