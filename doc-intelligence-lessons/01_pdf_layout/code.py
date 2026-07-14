"""Lesson 01 — PDF 解剖与版面解析
==================================
本脚本【纯本地、零 API】演示版面感知解析器怎么把 PDF 拆成带类型和坐标的元素流：
    ① 认清 PDF 的三层结构（文本层/图片对象/矢量绘图），演示「看得见字 ≠ 有文本层」
    ② 跑 parse_pdf，逐页打印元素类型统计（第 N 页：3 text + 1 image + 1 table）
    ③ 对比「朴素抽取（L00 天花板）vs 版面感知解析」在同一份毒文档上的差异

运行：python code.py
依赖：PyMuPDF(fitz)（venv 已装）；毒文档 data/multimodal_docs/company_briefing.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows GBK 坑：中文输出会 UnicodeEncodeError，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parents[2]
POISON_PDF = ROOT / "data" / "multimodal_docs" / "company_briefing.pdf"

# 复用 kb-qa 的解析器（课程产物，落地在 src/kb_qa/doc_parser.py）
sys.path.insert(0, str(ROOT / "portfolio-projects" / "knowledge-base-qa" / "src"))
from kb_qa.doc_parser import parse_pdf, summarize  # noqa: E402


# ══════════════════════════════════════════════════════════════════
# 1. PDF 三层结构体检：每页的文本层/图片/矢量绘图各多少
# ══════════════════════════════════════════════════════════════════
def inspect_pdf_layers(pdf_path: Path) -> None:
    """逐页打印 PDF 的三层构成：文本字符数 / 图片数 / 矢量线段数。

    这一步建立「看得见字 ≠ 有文本层」的认知——扫描页字符数=0、表格页线段多、
    图表页文本少但有图。版面感知解析的第一步就是分清这三种「看得见的内容」。
    """
    doc = fitz.open(str(pdf_path))
    print(f"{'页':<4} {'文本层(字)':<12} {'图片对象':<10} {'矢量线段':<10} {'判定':<16}")
    print("-" * 66)
    for i, page in enumerate(doc):
        txt = page.get_text().strip()
        n_img = len(page.get_images())
        n_lines = sum(
            1 for d in page.get_drawings() for item in d.get("items", []) if item and item[0] == "l"
        )
        # 三层构成的判定（和 doc_parser 的分类逻辑一致）
        if len(txt) == 0 and n_img > 0:
            verdict = "image（扫描页）"
        elif n_lines >= 6:
            verdict = "table（表格页）"
        elif n_img > 0 and len(txt) > 0:
            verdict = "mixed（图文混排）"
        else:
            verdict = "text（纯文本）"
        print(f"P{i+1:<3} {len(txt):<12} {n_img:<10} {n_lines:<10} {verdict}")
    doc.close()


# ══════════════════════════════════════════════════════════════════
# 2. 版面感知解析：parse_pdf 逐页元素流
# ══════════════════════════════════════════════════════════════════
def show_elements_by_page(pdf_path: Path) -> None:
    """跑 parse_pdf，逐页打印元素类型统计 + 每个元素的 bbox 和内容预览。"""
    elements = parse_pdf(pdf_path)
    rep = summarize(elements)
    print(f"\n解析结果：{rep.pages} 页 → {len(elements)} 个元素 "
          f"(text={rep.text_count}, table={rep.table_count}, image={rep.image_count})\n")

    # 按页分组
    by_page: dict[int, list] = {}
    for el in elements:
        by_page.setdefault(el.page, []).append(el)

    print(f"{'页':<4} {'元素':<32} {'说明'}")
    print("-" * 66)
    page_kinds = {1: "公司简介", 2: "考勤制度", 3: "保密协议(扫描)", 4: "薪酬表(表格)", 5: "经营数据(图表)", 6: "培训发展(混排)"}
    for p in sorted(by_page):
        els = by_page[p]
        type_counts = {}
        for e in els:
            type_counts[e.type] = type_counts.get(e.type, 0) + 1
        summary_str = " + ".join(f"{c} {t}" for t, c in type_counts.items())
        kind = page_kinds.get(p, "")
        print(f"P{p:<3} {summary_str:<30} {kind}")

    # 细节：扫描页和表格页的元素（最有教学价值的两个）
    print("\n── 关键元素明细（扫描页 + 表格页 + 图表图）──")
    for el in elements:
        if el.type == "image" and el.page == 3:
            print(f"  P{el.page} [image] bbox={tuple(round(v) for v in el.bbox)} content='<空>' "
                  f"→ 待 L03 OCR 填充")
        elif el.type == "table":
            preview = el.content[:40].replace("\n", " ")
            print(f"  P{el.page} [table] bbox={tuple(round(v) for v in el.bbox)} "
                  f"content='{preview}...' → 待 L02 结构化")
        elif el.type == "image" and el.page == 5:
            print(f"  P{el.page} [image] bbox={tuple(round(v) for v in el.bbox)} content='<空>' "
                  f"→ 待 L04 VLM 描述")


# ══════════════════════════════════════════════════════════════════
# 3. before/after 对比：朴素抽取 vs 版面感知
# ══════════════════════════════════════════════════════════════════
def compare_naive_vs_layout(pdf_path: Path) -> None:
    """同一份 PDF，两种看法的差异：
       - 朴素 get_text()：扫描页 0 字、表格串行化、图表数值不可见（L00 天花板）
       - 版面感知 parse_pdf：每类内容都认得出类型，带 bbox，可路由
    """
    doc = fitz.open(str(pdf_path))
    print(f"\n{'页':<4} {'朴素 get_text()':<22} {'版面感知 parse_pdf':<28} {'升级点'}")
    print("-" * 80)
    elements = parse_pdf(pdf_path)
    page_elements = {}
    for el in elements:
        page_elements.setdefault(el.page, []).append(el)

    for i, page in enumerate(doc):
        p = i + 1
        naive_chars = len(page.get_text().strip())
        naive_str = f"{naive_chars} 字"
        els = page_elements.get(p, [])
        type_counts = {}
        for e in els:
            type_counts[e.type] = type_counts.get(e.type, 0) + 1
        # 缩写：text→文, table→表, image→图（中文单字更清晰，避免 T 同时表 text/table）
        abbr = {"text": "文", "table": "表", "image": "图"}
        layout_str = " + ".join(f"{c}{abbr.get(t, t[0])}" for t, c in type_counts.items()) or "无元素"
        # 升级点
        if naive_chars == 0 and "image" in type_counts:
            upgrade = "🚫→✅ 认出是扫描页（待 OCR）"
        elif type_counts.get("table"):
            upgrade = "🚫→✅ 认出是表格（待结构化）"
        elif "image" in type_counts and naive_chars > 0:
            upgrade = "🚫→✅ 图文分离（图待 VLM）"
        else:
            upgrade = "（纯文本，无变化）"
        print(f"P{p:<3} {naive_str:<22} {layout_str:<28} {upgrade}")
    doc.close()


# ══════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════
def main() -> None:
    if not POISON_PDF.exists():
        print(f"[ERR] 找不到毒文档 {POISON_PDF}")
        print("      请先运行：python data/multimodal_docs/generate_poison_pdf.py")
        return

    print("=" * 66)
    print("演示 1：PDF 三层结构体检（文本层/图片/矢量绘图）")
    print("=" * 66)
    inspect_pdf_layers(POISON_PDF)

    print("\n" + "=" * 66)
    print("演示 2：版面感知解析 —— parse_pdf 逐页元素流")
    print("=" * 66)
    show_elements_by_page(POISON_PDF)

    print("\n" + "=" * 66)
    print("演示 3：before/after —— 朴素抽取 vs 版面感知")
    print("=" * 66)
    compare_naive_vs_layout(POISON_PDF)

    print("\n" + "=" * 66)
    print("结论：版面感知解析认出了三类杀手页的类型，但内容还没翻译")
    print("=" * 66)
    print("  text 元素  → 直接可用（走老路切块入库）")
    print("  table 元素 → content 还是串行文本（L02 用 pdfplumber 升级结构化）")
    print("  image 元素 → content 为空（L03 OCR / L04 VLM 描述填充）")
    print("  bbox 全程携带 → L06 的「页码+区域」引用溯源靠它")


if __name__ == "__main__":
    main()
