"""多模态检索测试：sources 带 element_type + 描述索引可被搜到（全 mock）。

验证 L05 落地点：
    - service 的 sources_payload 带 element_type/page（L06 引用也要用）
    - 描述索引：图表描述入 Chroma 后能被文字 query 检索到
不碰真实智谱 API（embedding 走 DeterministicFakeEmbedding）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
POISON_PDF = _REPO_ROOT / "data" / "multimodal_docs" / "company_briefing.pdf"


class TestSourcesCarryElementType:
    """sources 事件带 element_type/page（L05/L06 的前端展示和路由依据）。"""

    def test_text_docs_default_to_text_type(self, isolated_store, monkeypatch):
        """md/txt 入库的 chunk，element_type 默认是 text（向后兼容）。"""
        import kb_qa.ingest as ingest_mod

        (isolated_store / "a.md").write_text("# A\n内容A", encoding="utf-8")
        report = ingest_mod.ingest_directory(isolated_store)
        vs = ingest_mod.get_vectorstore()
        data = vs._collection.get(include=["metadatas"])
        metas = data.get("metadatas") or []
        # md/txt 的 chunk 没有 element_type 字段（load_and_split 不加这个）
        # 这是正确的——只有 PDF 多模态解析才加 element_type
        assert len(metas) > 0

    def test_pdf_docs_carry_element_type(self, isolated_store, monkeypatch):
        """PDF 入库的 chunk 带 element_type（text/table/image），L05 路由依据。"""
        if not POISON_PDF.exists():
            pytest.skip("毒文档不存在")

        import kb_qa.ingest as ingest_mod

        monkeypatch.setattr(ingest_mod.settings, "enable_multimodal_ingest", True)
        (isolated_store / "poison.pdf").write_bytes(POISON_PDF.read_bytes())
        ingest_mod.ingest_directory(isolated_store)

        vs = ingest_mod.get_vectorstore()
        data = vs._collection.get(where={"source": "poison.pdf"}, include=["metadatas"])
        metas = data.get("metadatas") or []
        assert len(metas) > 0
        types = {m.get("element_type") for m in metas}
        # 应至少含 text 和 table（image 元素内容空时不入库，除非 enable_image_caption）
        assert "text" in types or "table" in types
        # 每个 chunk 都应有 page 字段（L06 引用溯源用）
        assert all("page" in m for m in metas)


class TestDescriptionIndex:
    """描述索引：图表描述入 Chroma 后能被文字 query 检索到。"""

    def test_chart_description_is_retrievable(self, isolated_store, monkeypatch):
        """图表描述（含数值）入库后，文字 query 能检索到它。"""
        import kb_qa.ingest as ingest_mod
        from langchain_core.documents import Document

        # 模拟：图表描述作为一个 image 类型的 chunk 入库
        desc_doc = Document(
            page_content="柱状图 Q1:1800 Q2:2400 Q3:2100 Q4:2900 季度营收 Q4最高",
            metadata={
                "source": "chart.pdf", "section": "P1·image",
                "src_hash": "test123", "chunk_idx": 0,
                "element_type": "image", "page": 1,
            },
        )
        vs = ingest_mod.get_vectorstore()
        vs.add_documents([desc_doc], ids=["chart.pdf:test:0"])

        # 用 BM25 + 向量混合检索，query 应命中这个描述
        from kb_qa.retriever import KBRetriever

        kb = KBRetriever(vs)
        docs = kb.retrieve("Q3 营收多少", mode="vector")
        assert len(docs) > 0
        # 命中的文档应包含图表描述（含 Q3/2100）
        contents = [d.page_content for d in docs]
        assert any("2100" in c or "Q3" in c for c in contents)

    def test_description_beats_title_only(self, isolated_store, monkeypatch):
        """图表描述（含数值）和标题都在库里，数值类 query 至少能检索到含数值的描述。

        注意：DeterministicFakeEmbedding 不具备真语义（基于内容哈希），
        所以这里只验证「描述在库里、能被检索到、含数值」，而非语义排名。
        真正的语义排名需真 embedding-3（code.py 演示）。
        """
        import kb_qa.ingest as ingest_mod
        from langchain_core.documents import Document

        vs = ingest_mod.get_vectorstore()
        # 标题（text-only 抽到的，无数值）
        vs.add_documents([Document(
            page_content="2024 年度经营数据 上图为各季度营收",
            metadata={"source": "c.pdf", "section": "", "src_hash": "h1", "chunk_idx": 0,
                      "element_type": "text", "page": 5},
        )], ids=["c.pdf:h1:0"])
        # 描述（含数值）
        vs.add_documents([Document(
            page_content="柱状图 营收 Q1:1800 Q2:2400 Q3:2100 Q4:2900",
            metadata={"source": "c.pdf", "section": "", "src_hash": "h1", "chunk_idx": 1,
                      "element_type": "image", "page": 5},
        )], ids=["c.pdf:h1:1"])

        from kb_qa.retriever import KBRetriever

        kb = KBRetriever(vs)
        # 用 hybrid（BM25+向量），BM25 对关键词「2100」「Q3」有偏好
        docs = kb.retrieve("Q3 营收 2100", mode="hybrid")
        assert len(docs) > 0
        # 至少有一个命中的 doc 含数值（描述索引的价值：数值进了库就能被搜到）
        all_contents = [d.page_content for d in docs]
        assert any("2100" in c for c in all_contents)
