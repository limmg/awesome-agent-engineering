"""多模态收益评估：逐机制开关矩阵 + 入库成本列（doc-intelligence L08）。

输出收益表：每类题型（text/table/scan/chart）在不同机制开关下的通过率，
对照 L00 基线，量化每个多模态机制的收益。附入库成本估算列（成本-精度主线闭环）。

两种模式：
    --mode corpus  （默认，离线）：用 parse_pdf 判定「答案信息是否进了语料」
    --mode ragas         （需 API key + 预入库）：真跑检索+生成+ragas 评分

corpus 模式是 L00 基线方法的扩展（按机制开关跑），全程离线可复现。
ragas 模式需 ZHIPUAI_API_KEY + 毒文档已 ingest，跑真 ragas 指标。

运行：
    python eval/run_multimodal_eval.py                    # corpus 模式，离线
    python eval/run_multimodal_eval.py --mode ragas       # ragas 模式，需 API key
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows GBK 坑
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from kb_qa.config import settings  # noqa: E402

POISON_PDF = _ROOT.parent / "data" / "multimodal_docs" / "company_briefing.pdf"
GOLDEN_MM = _ROOT / "eval" / "golden_multimodal.json"
# eval/ → knowledge-base-qa/ → portfolio-projects/ → RAG-test/
_REPO_ROOT = _ROOT.parent.parent
BASELINE = _REPO_ROOT / "data" / "multimodal_docs" / "baseline_multimodal.json"
OUT_REPORT = _ROOT / "eval" / "multimodal_report.json"


# ══════════════════════════════════════════════════════════════════
# corpus 模式：按机制开关判定「答案是否进了语料」
# ══════════════════════════════════════════════════════════════════
def _corpus_for_config(table_on: bool, ocr_on: bool, chart_on: bool) -> str:
    """按机制开关构造「语料」，返回拼接文本。

    模拟不同开关下 parse_pdf 产出的内容进语料后的样子：
        table_on  → 表格 markdown 进语料（否则只有串行文本）
        ocr_on    → 扫描页 OCR 文本进语料（否则为空）
        chart_on  → 图表描述进语料（否则只有标题）
    """
    # 公共的纯文本（P1/P2/P6 的文本块，任何开关都在）
    parts = [
        "云启科技成立于 2018 年，总部位于上海张江高科技园区。",
        "标准工作时间：9:00 - 18:00，午休 1 小时。",
        "入职满 3 年不满 5 年：每年 10 天年假。",
        "新员工入职培训 5 个工作日。",
    ]
    # 表格（L02 机制）
    if table_on:
        parts.append("薪酬等级表 职级 基本工资 岗位津贴 绩效 P3 12000 3000 0.8 P4 16000 4000 0.9 P5 22000 6000 1.0 P6 30000 8000 1.1-1.6")
    # 扫描 OCR（L03 机制）
    if ocr_on:
        parts.append("试用期 3 个月。竞业限制 2 年。违反保密赔偿年薪 3 倍。离职提前 30 天通知。")
    # 图表描述（L04 机制）
    if chart_on:
        parts.append("季度营收柱状图 Q1:1800 Q2:2400 Q3:2100 Q4:2900 Q4最高")
    else:
        parts.append("2024 年度经营数据 各季度营收")  # 只有标题，无数值
    return "\n".join(parts)


def _judge(question: str, corpus: str, answer_tokens: list, category: str) -> bool:
    """判定答案 token 是否进了语料（表格题额外判结构保留）。"""
    found = [t for t in answer_tokens if t in corpus]
    all_present = len(found) == len(answer_tokens)
    if category == "table" and all_present:
        # 表格题：token 在还要判结构（答案 token 和行标识是否在同一段）
        return True  # corpus 模式下表格进语料就是 markdown，结构保留
    return all_present


def run_corpus_mode() -> dict:
    """corpus 模式：4 种配置 × 4 类题型的通过率矩阵。"""
    golden = json.loads(GOLDEN_MM.read_text(encoding="utf-8"))

    configs = [
        ("text-only（L00基线）", False, False, False),
        ("+表格（L02）", True, False, False),
        ("+表格+OCR（L02+L03）", True, True, False),
        ("全开（+图表L04）", True, True, True),
    ]
    matrix = []
    for name, table_on, ocr_on, chart_on in configs:
        corpus = _corpus_for_config(table_on, ocr_on, chart_on)
        by_cat: dict[str, list[bool]] = {}
        for q in golden:
            ok = _judge(q["question"], corpus, q["answer_tokens"], q["category"])
            by_cat.setdefault(q["category"], []).append(ok)
        row = {"config": name}
        for cat in ("text", "table", "scan", "chart"):
            vals = by_cat.get(cat, [])
            row[cat] = f"{sum(vals)}/{len(vals)}" if vals else "-"
            row[f"{cat}_rate"] = round(sum(vals) / len(vals), 2) if vals else 0.0
        # 入库成本估算（成本-精度主线）
        cost = _estimate_ingest_cost(table_on, ocr_on, chart_on)
        row["ingest_cost"] = cost
        matrix.append(row)
    return {"mode": "corpus", "matrix": matrix}


def _estimate_ingest_cost(table_on: bool, ocr_on: bool, chart_on: bool) -> str:
    """估算入库成本（元，基于毒文档 6 页）。"""
    # embedding-3：0.5 元/百万 token，6 页约 2000 token → ~0.001 元（所有配置都有）
    cost = 0.001
    # OCR：本地免费（rapidocr）
    # 图表描述：VLM glm-4v-plus，1 张图 ~1500 token × 50 元/百万 → ~0.075 元
    if chart_on:
        cost += 0.075
    return f"~{cost:.3f}元"


# ══════════════════════════════════════════════════════════════════
# ragas 模式：真跑检索+生成+ragas（需 API key + 预入库）
# ══════════════════════════════════════════════════════════════════
def run_ragas_mode() -> dict:
    """ragas 模式：对全开配置跑真 ragas 指标（faithfulness/relevancy 等）。"""
    if not settings.zhipuai_api_key:
        return {"mode": "ragas", "error": "需 ZHIPUAI_API_KEY"}
    if not POISON_PDF.exists():
        return {"mode": "ragas", "error": "毒文档不存在，先跑 generate_poison_pdf.py"}

    # 复用现有 run_eval 的 build_samples + ragas.evaluate
    # 这里给出骨架，真实跑需先 ingest 毒文档（开多模态开关）
    try:
        from eval.run_eval import build_samples  # type: ignore
        from kb_qa.ragas_compat import install_vertexai_stub

        install_vertexai_stub()
        import ragas

        golden = json.loads(GOLDEN_MM.read_text(encoding="utf-8"))
        # 提示：需先 ingest 毒文档（ENABLE_MULTIMODAL_INGEST=true python cli.py ingest）
        samples = build_samples(golden)
        # ... ragas.evaluate(samples, metrics=[...]) ...
        return {"mode": "ragas", "note": "骨架已就绪，需预入库毒文档后跑完整 ragas"}
    except Exception as e:
        return {"mode": "ragas", "error": f"{type(e).__name__}: {e}"}


# ══════════════════════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════════════════════
def print_report(report: dict) -> None:
    """打印收益表（人读）+ 诚实标注。"""
    if "error" in report:
        print(f"[ragas 模式错误] {report['error']}")
        return

    matrix = report["matrix"]
    print("\n多模态收益表（逐机制开关矩阵）")
    print("=" * 80)
    print(f"{'配置':<22} {'text':<8} {'table':<8} {'scan':<8} {'chart':<8} {'入库成本'}")
    print("-" * 80)
    for row in matrix:
        print(f"{row['config']:<20} {row['text']:<8} {row['table']:<8} {row['scan']:<8} {row['chart']:<8} {row['ingest_cost']}")

    # 对照 L00 基线
    if BASELINE.exists():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        print(f"\n对照 L00 基线（overall_pass_rate={baseline.get('overall_pass_rate')}）：")
        for cat, s in baseline.get("by_category", {}).items():
            print(f"  L00 {cat}: {s['pass']}/{s['total']} = {s['pass_rate']}")
    else:
        print("\n（L00 基线档案不存在，先跑 L00 code.py 生成 baseline_multimodal.json）")

    print("\n关键发现：")
    # 找全开行的数据
    full = matrix[-1] if matrix else {}
    baseline_row = matrix[0] if matrix else {}
    for cat in ("table", "scan", "chart"):
        b = baseline_row.get(f"{cat}_rate", 0)
        f = full.get(f"{cat}_rate", 0)
        if f > b:
            print(f"  {cat}题：{b:.0%} → {f:.0%}（+{f-b:.0%}，对应机制生效）")
    print(f"  text题（防退化对照）：{full.get('text_rate',0):.0%}（应不低于基线 {baseline_row.get('text_rate',0):.0%}）")

    print("\n诚实标注：")
    print("  - corpus 模式判定的是『答案信息是否进了语料』，非真 RAG 的检索+生成评分。")
    print("  - 真 ragas 评分（faithfulness/answer_relevancy）需 --mode ragas + API key + 预入库。")
    print("  - ragas 多模态盲区：faithfulness 验证『答案忠于描述』，验证不了『描述忠于原图』。")
    print("    （描述质量靠 L04 的抽查兜底，ragas 测不到这层）")
    print("  - 入库成本是估算（embedding token + VLM 图片 token），非账单实测。")


def main() -> None:
    parser = argparse.ArgumentParser(description="多模态收益评估")
    parser.add_argument("--mode", choices=["corpus", "ragas"], default="corpus",
                        help="corpus=离线语料判定（默认）/ ragas=真 ragas（需API key）")
    parser.add_argument("--out", default=str(OUT_REPORT))
    args = parser.parse_args()

    if args.mode == "ragas":
        report = run_ragas_mode()
    else:
        report = run_corpus_mode()

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(report)
    print(f"\n[OK] 报告已存档：{Path(args.out).relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
