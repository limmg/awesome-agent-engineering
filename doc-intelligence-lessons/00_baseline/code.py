"""Lesson 00 — 全景与基线：文本 RAG 的天花板
==================================================
本脚本【纯本地、零 API】演示一件事：把一份「混合 PDF」丢给只认文本层的管线，
会发生什么。三步：
    ① 用 PyMuPDF 的文本层抽取，逐页打印抽到的字符量（扫描页≈0，是失败起点）
    ② 把抽到的全部文本拼成一个「语料」，模拟现状 kb-qa 的入库视角
    ③ 对 17 道 golden 题做关键词命中判定（无需真 LLM），存档 baseline_multimodal.json

运行：python code.py
依赖：PyMuPDF(fitz)（venv 已装）；毒文档 data/multimodal_docs/company_briefing.pdf
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Windows GBK 坑：中文输出会 UnicodeEncodeError，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import fitz  # PyMuPDF

# 路径：本脚本在 doc-intelligence-lessons/00_baseline/，毒文档在仓库根 data/
ROOT = Path(__file__).resolve().parents[2]
POISON_PDF = ROOT / "data" / "multimodal_docs" / "company_briefing.pdf"
GOLDEN_JSON = ROOT / "data" / "multimodal_docs" / "golden_questions.json"
OUT_BASELINE = ROOT / "data" / "multimodal_docs" / "baseline_multimodal.json"


# ══════════════════════════════════════════════════════════════════
# 1. 文本层抽取：模拟「只吃文本」的管线怎么看这份 PDF
# ══════════════════════════════════════════════════════════════════
def extract_text_layer(pdf_path: Path) -> list[str]:
    """逐页用 PyMuPDF 抽文本层。返回每页文本的列表（扫描页≈空串）。

    这一步模拟的是：现状 kb-qa 的 loader 只认 .md/.txt，若硬要把 PDF 文本层喂进去，
    PyMuPDF 的 get_text() 就是业界「最朴素的抽取」。扫描页抽到空、表格抽到乱序串、
    图表的数值根本不在文本层——全在这里暴露。
    """
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    doc.close()
    return pages


# ══════════════════════════════════════════════════════════════════
# 2. 关键词命中判定：离线、可复现的「裸基线」评分
# ══════════════════════════════════════════════════════════════════
def keyword_hit(question: str, corpus: str, answer_tokens: list[str], category: str) -> dict:
    """最朴素的判定：答案的关键 token 是否出现在语料里。

    这不是「检索+生成」的完整 RAG，而是把语料当一堆文本、问「答案在不在里面」。
    对于纯文本题，答案 token 在语料里 → 命中（模拟「能答对」）；
    对于扫描/图表题，答案 token 根本没被抽进语料 → miss（模拟「答不出」）；
    对于表格题，原始数字可能「碰巧」在串行化文本里，但行/列对应关系已丢失——
    LLM 拿到一坨 `P3\\n12000\\n3000\\n...` 根本无法判断哪个数属于哪一列，
    所以表格题用「带列名上下文的命中」判定：答案 token 必须和它所属的列标签
    （如「基本工资」）出现在同一段连续上下文里，否则算结构丢失 FAIL。
    """
    found = [tok for tok in answer_tokens if tok in corpus]
    all_present = len(found) == len(answer_tokens)

    if category == "table":
        # 表格题的真失败模式是「结构丢失」：数字在，但没法和列对上。
        # 串行化后整页文本是一长串数字+列名混杂，列名和数字之间被换行打散。
        # 判定：答案 token 出现位置附近 ±30 字内是否有其所属列名。没有就 FAIL。
        column_hints = {
            "基本工资": "基本工资", "岗位津贴": "岗位津贴", "绩效": "绩效",
        }
        hint = next((v for k, v in column_hints.items() if k in question), None)
        if hint:
            struct_ok = all(
                any(corpus[max(0, idx - 30): idx + 30].find(hint) >= 0
                    for idx in _all_indices(corpus, tok))
                for tok in answer_tokens if tok in corpus
            )
            verdict = "PASS" if (all_present and struct_ok) else "FAIL"
        else:
            verdict = "PASS" if all_present else "FAIL"
    else:
        verdict = "PASS" if all_present else "FAIL"

    return {
        "answer_tokens": answer_tokens,
        "found_in_corpus": found,
        "all_present": all_present,
        "verdict": verdict,
        "note": "表格结构丢失：数字在但列对应被打散" if (category == "table" and verdict == "FAIL") else "",
    }


def _all_indices(haystack: str, needle: str) -> list[int]:
    """返回 needle 在 haystack 中所有出现位置（generator 友好）。"""
    if not needle:
        return []
    idxs = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            break
        idxs.append(idx)
        start = idx + 1
    return idxs


# ══════════════════════════════════════════════════════════════════
# 3. 跑基线：把语料拼起来，逐题判定，分类统计，存档
# ══════════════════════════════════════════════════════════════════
def run_baseline(pdf_path: Path, golden_path: Path, out_path: Path) -> dict:
    pages_text = extract_text_layer(pdf_path)
    corpus = "\n".join(pages_text)  # 模拟「全部文本入库后能被搜到的池子」

    questions = json.loads(golden_path.read_text(encoding="utf-8"))
    results = []
    by_cat: dict[str, list[str]] = {}

    for q in questions:
        # 关键：判定时只看「该题答案所在页」被抽到了多少文本。
        # 扫描页/图表页的答案本该出现在那一页，但该页文本层为空或不含数值 → FAIL。
        # 这比「全语料子串匹配」更诚实：避免 30000 里的 '30' 被误判成扫描题答对。
        page_idx = q["source_page"] - 1
        page_text = pages_text[page_idx] if 0 <= page_idx < len(pages_text) else ""
        # 表格题仍用整页语料做结构检查（表头和数据在同页）
        r = keyword_hit(q["question"], page_text, q["answer_tokens"], q["category"])
        entry = {
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "expected_answer": q["answer"],
            "source_page": q["source_page"],
            "page_text_chars": len(page_text),
            **r,
        }
        results.append(entry)
        by_cat.setdefault(q["category"], []).append(r["verdict"])

    # 分类汇总
    summary = {}
    for cat, verdicts in by_cat.items():
        passed = verdicts.count("PASS")
        total = len(verdicts)
        summary[cat] = {
            "total": total,
            "pass": passed,
            "fail": total - passed,
            "pass_rate": round(passed / total, 2) if total else 0.0,
        }

    report = {
        "lesson": "L00 baseline",
        "method": "PyMuPDF 文本层抽取 + 答案 token 是否出现在语料（关键词命中，非真 RAG）",
        "honest_note": "mock 评分：无真实检索/生成，仅验证『答案信息是否进了语料池』。扫描/图表题的 token 不在文本层 → FAIL，正是要量化的天花板。",
        "source_pdf": str(pdf_path.relative_to(ROOT)),
        "pages_char_count": [len(t) for t in pages_text],
        "corpus_total_chars": len(corpus),
        "by_category": summary,
        "overall_pass_rate": round(
            sum(1 for r in results if r["verdict"] == "PASS") / len(results), 3
        ),
        "results": results,
    }

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# ══════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 66)
    print("演示 1：文本层抽取 —— 只吃文本的管线怎么看这份混合 PDF")
    print("=" * 66)
    if not POISON_PDF.exists():
        print(f"[ERR] 找不到毒文档 {POISON_PDF}")
        print("      请先运行：python data/multimodal_docs/generate_poison_pdf.py")
        return
    pages_text = extract_text_layer(POISON_PDF)
    page_kinds = ["纯文本(公司简介)", "纯文本(考勤制度)", "扫描页(保密协议)", "表格页(薪酬表)", "图表页(营收)", "图文混排(培训)"]
    print(f"{'页':<4} {'内容':<20} {'抽到字符':<10} {'图片':<6} 失败模式")
    print("-" * 66)
    for i, (txt, kind) in enumerate(zip(pages_text, page_kinds)):
        doc = fitz.open(str(POISON_PDF))
        n_img = len(doc[i].get_images())
        doc.close()
        fail = ""
        if i == 2 and len(txt) == 0:
            fail = "🚫 完全无文本(扫描)"
        elif i == 3:
            fail = "🚫 数字在但结构丢失(串行化)"
        elif i == 4 and "1800" not in txt:
            fail = "🚫 图表数值不在文本(不可见)"
        else:
            fail = "✅ 正常"
        print(f"P{i+1:<3} {kind:<18} {len(txt):<10} {n_img:<6} {fail}")

    print()
    print("=" * 66)
    print("演示 2：拼成语料，跑 17 道 golden 题的裸基线（关键词命中）")
    print("=" * 66)
    report = run_baseline(POISON_PDF, GOLDEN_JSON, OUT_BASELINE)

    print(f"\n语料总字符数：{report['corpus_total_chars']}")
    print(f"各页字符数：{report['pages_char_count']}\n")
    print(f"{'分类':<8} {'题数':<6} {'通过':<6} {'通过率':<8}")
    print("-" * 40)
    for cat, s in report["by_category"].items():
        flag = "✅" if s["pass_rate"] == 1.0 else ("🚫" if s["pass_rate"] == 0.0 else "⚠️")
        print(f"{cat:<8} {s['total']:<6} {s['pass']:<6} {s['pass_rate']:<8} {flag}")

    print("-" * 40)
    print(f"总体通过率：{report['overall_pass_rate']}（{sum(1 for r in report['results'] if r['verdict']=='PASS')}/{len(report['results'])}）")
    print(f"\n[OK] 基线已存档：{OUT_BASELINE.relative_to(ROOT)}")
    print("     后面每课落地后重跑对应题型，对照这份基线看收益。")

    print()
    print("=" * 66)
    print("演示 3：逐题明细（哪些题挂了、为什么挂）")
    print("=" * 66)
    for r in report["results"]:
        mark = "✅" if r["verdict"] == "PASS" else "🚫"
        if r["verdict"] == "PASS":
            reason = ""
        elif r.get("note"):
            reason = f"  → {r['note']}"
        else:
            missing = [t for t in r["answer_tokens"] if t not in r["found_in_corpus"]]
            reason = f"  → 该页文本层抽不到: {missing}"
        print(f"{mark} [{r['category']:<5}] {r['question']}")
        if reason:
            print(f"   {reason}")


if __name__ == "__main__":
    main()
