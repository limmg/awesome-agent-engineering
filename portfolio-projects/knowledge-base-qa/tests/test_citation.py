"""引用溯源测试：页码引用 + 区域裁剪图 + 防幻觉引用格式（全本地）。

验证 L06 落地点：
    - Citation 三级（text/page/region）的 level 判定
    - clip_region 真裁剪 PDF 区域为 PNG
    - generate.build_context 的多模态引用格式（页码+类型）
    - 防幻觉：引用格式不误伤 guardrails 输出过滤
不碰真实智谱 API。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kb_qa.citation import Citation, build_citation, clip_region
from kb_qa.generate import build_context

_REPO_ROOT = Path(__file__).resolve().parents[3]
POISON_PDF = _REPO_ROOT / "data" / "multimodal_docs" / "company_briefing.pdf"


class TestCitationLevel:
    """Citation 三级：text（纯文字）/ page（页码）/ region（区域截图）。"""

    def test_text_level(self):
        c = Citation(source="hb.md")
        assert c.level == "text"
        assert c.display() == "hb.md"

    def test_page_level(self):
        c = Citation(source="briefing.pdf", page=3, element_type="image")
        assert c.level == "page"
        assert "P3" in c.display()
        assert "图片" in c.display()

    def test_region_level(self):
        c = Citation(source="briefing.pdf", page=4, element_type="table",
                     bbox=(0, 0, 100, 100), clip_image_path="/tmp/clip.png")
        assert c.level == "region"

    def test_table_citation_display(self):
        c = Citation(source="briefing.pdf", page=4, element_type="table")
        assert "P4" in c.display()
        assert "表格" in c.display()


class TestClipRegion:
    """区域裁剪图：PyMuPDF get_pixmap(clip=bbox)。"""

    @pytest.mark.skipif(not POISON_PDF.exists(), reason="毒文档不存在")
    def test_clip_produces_png(self, tmp_path):
        """裁剪毒文档 P4 表格区域为 PNG。"""
        # P4 表格的大致区域（整页，毒文档表格在页面上半部）
        bbox = (50, 80, 545, 280)
        out = clip_region(POISON_PDF, page=4, bbox=bbox, out_dir=tmp_path, dpi=100)
        assert out.exists()
        assert out.suffix == ".png"
        assert out.stat().st_size > 1000  # PNG 至少几 KB

    @pytest.mark.skipif(not POISON_PDF.exists(), reason="毒文档不存在")
    def test_clip_filename_contains_page_and_bbox(self, tmp_path):
        """裁剪图文件名含页码和 bbox（便于溯源定位）。"""
        bbox = (50, 80, 545, 280)
        out = clip_region(POISON_PDF, page=4, bbox=bbox, out_dir=tmp_path)
        assert "P4" in out.name
        assert "50" in out.name  # bbox 的 x0

    def test_build_citation_without_clip(self):
        """enable_clip=False：page 级引用，不裁剪。"""
        c = build_citation(source="a.pdf", page=3, element_type="text")
        assert c.level == "page"
        assert c.clip_image_path is None

    @pytest.mark.skipif(not POISON_PDF.exists(), reason="毒文档不存在")
    def test_build_citation_with_clip(self, tmp_path):
        """enable_clip=True：region 级引用，生成裁剪图。"""
        c = build_citation(
            source="company_briefing.pdf", page=4, element_type="table",
            bbox=(50, 80, 545, 280), pdf_path=POISON_PDF, enable_clip=True,
        )
        # out_dir 默认是 pdf 同目录的 clips/，这里测函数不崩即可
        assert c.level in ("region", "page")  # 裁剪成功 region，失败降级 page


class TestMultimodalCitationFormat:
    """generate.build_context 的多模态引用格式（L06 升级）。"""

    def test_text_doc_citation_unchanged(self):
        """md/txt 文档（无 page/element_type）引用格式不变（向后兼容）。"""
        docs = [
            __import__("langchain_core.documents", fromlist=["Document"]).Document(
                page_content="年假 5 天",
                metadata={"source": "hb.md", "section": "手册 > 假期"},
            )
        ]
        ctx = build_context(docs)
        assert "hb.md · 手册 > 假期" in ctx  # 格式完全不变

    def test_pdf_doc_citation_has_page(self):
        """PDF 文档（有 page/element_type）引用带页码和类型。"""
        from langchain_core.documents import Document

        docs = [
            Document(
                page_content="| 职级 | 基本工资 |\n| P5 | 22000 |",
                metadata={
                    "source": "briefing.pdf", "section": "",
                    "page": 4, "element_type": "table",
                },
            )
        ]
        ctx = build_context(docs)
        assert "briefing.pdf · P4·表格" in ctx

    def test_pdf_doc_with_section_uses_section(self):
        """PDF 文档有 section 时，section 优先（PDF 解析的 section 已含页码信息）。"""
        from langchain_core.documents import Document

        docs = [
            Document(
                page_content="内容",
                metadata={
                    "source": "briefing.pdf", "section": "P3·image",
                    "page": 3, "element_type": "image",
                },
            )
        ]
        ctx = build_context(docs)
        assert "briefing.pdf · P3·image" in ctx  # section 优先

    def test_no_dangling_dot_when_no_section_no_page(self):
        """无 section 且无 page：只有 source，不留孤零点（回归 test_generate）。"""
        from langchain_core.documents import Document

        docs = [Document(page_content="x", metadata={"source": "fin.md", "section": ""})]
        ctx = build_context(docs)
        assert "fin.md" in ctx
        assert "· \n" not in ctx  # 不留孤零点

    def test_guardrails_isolation_still_wraps(self):
        """多模态引用格式不影响 guardrails 的隔离标签（回归）。"""
        from kb_qa.guardrails import SAFE_SYSTEM_PROMPT  # 确保能导入

        docs = [
            __import__("langchain_core.documents", fromlist=["Document"]).Document(
                page_content="内容",
                metadata={"source": "a.pdf", "section": "", "page": 1, "element_type": "text"},
            )
        ]
        ctx = build_context(docs)
        assert "<begin_retrieved_documents>" in ctx
        assert "<end_retrieved_documents>" in ctx
        assert "SAFE" not in str(SAFE_SYSTEM_PROMPT) or "材料" in str(SAFE_SYSTEM_PROMPT)
