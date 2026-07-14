"""Lesson 06 — 引用溯源升级：回到原文档
==================================================
把引用从「chunk 文本」升级到「文档+页码+区域(bbox)」，完成可信度三部曲第三步。
    ① 引用格式升级：纯文字 → 页码引用（文档 P3·表格）
    ② 区域裁剪图：PyMuPDF clip=bbox 裁剪原图区域（最可信引用）
    ③ 防幻觉强化：数字类答案必须给出处，给不出就答「材料中未找到」

可信度三部曲：frontier 让数字可复算、gui 让来源可回访、本课让引用可回溯。

运行：python code.py
依赖：PyMuPDF（venv 已装）；毒文档 data/multimodal_docs/
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows GBK 坑：中文输出会 UnicodeEncodeError，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
POISON_PDF = ROOT / "data" / "multimodal_docs" / "company_briefing.pdf"
sys.path.insert(0, str(ROOT / "portfolio-projects" / "knowledge-base-qa" / "src"))
from kb_qa.citation import Citation, build_citation, clip_region  # noqa: E402
from kb_qa.generate import build_context  # noqa: E402


# ══════════════════════════════════════════════════════════════════
# 1. 引用格式升级演示
# ══════════════════════════════════════════════════════════════════
def show_citation_levels() -> None:
    """三级引用：text（纯文字）→ page（页码）→ region（区域截图）。"""
    print("  ① 纯文字引用（text 级，旧格式）:")
    c1 = Citation(source="employee_handbook.md")
    print(f"     {c1.display()}  [level={c1.level}]")

    print("\n  ② 页码引用（page 级，L06 默认）:")
    c2 = Citation(source="company_briefing.pdf", page=4, element_type="table")
    print(f"     {c2.display()}  [level={c2.level}]")

    print("\n  ③ 区域截图引用（region 级，最可信）:")
    c3 = Citation(source="company_briefing.pdf", page=4, element_type="table",
                  bbox=(50, 80, 545, 280), clip_image_path="clips/briefing_P4_50_80_545_280.png")
    print(f"     {c3.display()} + 裁剪图  [level={c3.level}]")


# ══════════════════════════════════════════════════════════════════
# 2. 区域裁剪图：真裁剪毒文档表格区域
# ══════════════════════════════════════════════════════════════════
def show_region_clip() -> Path | None:
    """裁剪毒文档 P4 表格区域为 PNG，演示「最可信引用」。"""
    if not POISON_PDF.exists():
        print("  [跳过] 毒文档不存在")
        return None
    # P4 表格区域（薪酬表在页面上半部）
    bbox = (50, 80, 545, 280)
    out = clip_region(POISON_PDF, page=4, bbox=bbox, dpi=150)
    print(f"  裁剪图已生成: {out.relative_to(ROOT)}")
    print(f"  文件大小: {out.stat().st_size / 1024:.0f}KB")
    print(f"  用户看到答案「P5 基本工资 22000」时，可点开裁剪图核对原图区域")
    return out


# ══════════════════════════════════════════════════════════════════
# 3. 多模态引用进上下文（generate.build_context）
# ══════════════════════════════════════════════════════════════════
def show_context_with_multimodal_citations() -> None:
    """演示检索材料进 prompt 时的引用格式（旧 vs 新）。"""
    from langchain_core.documents import Document

    print("  ── 旧格式（纯文本文档，md/txt）──")
    old_docs = [
        Document(page_content="年假 5 天起", metadata={"source": "hb.md", "section": "手册 > 假期"}),
    ]
    ctx_old = build_context(old_docs)
    for line in ctx_old.split("\n")[:2]:
        print(f"     {line}")

    print("\n  ── 新格式（多模态文档，PDF 带页码+类型）──")
    new_docs = [
        Document(page_content="| P5 | 22000 | 6000 |", metadata={
            "source": "briefing.pdf", "section": "", "page": 4, "element_type": "table"}),
        Document(page_content="试用期3个月", metadata={
            "source": "briefing.pdf", "section": "", "page": 3, "element_type": "image"}),
    ]
    ctx_new = build_context(new_docs)
    for line in ctx_new.split("\n")[:4]:
        if line.strip():
            print(f"     {line}")


# ══════════════════════════════════════════════════════════════════
# 4. 防幻觉强化：数字类答案必须给出处
# ══════════════════════════════════════════════════════════════════
def show_anti_hallucination() -> None:
    """数字类答案必须给出处元素，给不出就答「材料中未找到」。"""
    # 模拟两个场景：有出处 vs 无出处
    cases = [
        ("P5 基本工资多少？", "22000", True, "briefing.pdf · P4·表格"),
        ("公司市值多少？", None, False, "（材料中未找到）"),
    ]
    print(f"\n  {'问题':<18} {'答案':<10} {'有出处':<8} {'引用'}")
    print("  " + "-" * 60)
    for q, ans, has_src, cite in cases:
        mark = "✅ 答且有出处" if has_src else "🚫 拒答（无出处）"
        print(f"  {q:<16} {str(ans):<10} {mark:<12} {cite}")
    print("\n  → 防幻觉纪律（延续 rag-L05）：数字给不出出处就答「材料中未找到」")


# ══════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 66)
    print("演示 1：引用三级 —— text → page → region")
    print("=" * 66)
    show_citation_levels()

    print("\n" + "=" * 66)
    print("演示 2：区域裁剪图 —— 最可信引用（真裁剪毒文档）")
    print("=" * 66)
    show_region_clip()

    print("\n" + "=" * 66)
    print("演示 3：多模态引用进上下文（generate.build_context）")
    print("=" * 66)
    show_context_with_multimodal_citations()

    print("\n" + "=" * 66)
    print("演示 4：防幻觉强化 —— 数字必须给出处")
    print("=" * 66)
    show_anti_hallucination()

    print("\n" + "=" * 66)
    print("可信度三部曲")
    print("=" * 66)
    print("  ① frontier：数字【可复算】—— 代码解释器让计算过程透明")
    print("  ② gui：来源【可回访】—— 浏览器证据链让网页引用可点开")
    print("  ③ 本课：引用【可回溯】—— 页码+区域让多模态引用回到原图")
    print("\n  → 多模态材料都是转换的产物（OCR/VLM/表格抽取），转换就会错")
    print("  → 所以必须能一键回到原始位置核对，否则可信度崩塌")


if __name__ == "__main__":
    main()
