"""检索层：BM25+向量混合召回 → 智谱 rerank 重排 → 引用材料列表。

为什么混合检索（rag-06 的 RRF 思路生产版）：
    向量检索吃语义（「工资的八成」≈「转正工资的 80%」），但对精确词弱
    （产品名「帆修」、编号「P0」这类 token 向量容易糊）；
    BM25 恰好相反。EnsembleRetriever 用加权 RRF 融合两路，互补短板。

中文 BM25 的坑：BM25 默认按空格分词，中文整句会变成一个 token 直接失效，
必须用 jieba 分词作为 preprocess_func。
"""
from __future__ import annotations

import jieba
from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.multi_query import MultiQueryRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from .config import settings
from .ingest import get_vectorstore
from .llm import get_chat_model
from .rerank import rerank_documents


def _tokenize_zh(text: str) -> list[str]:
    """jieba 中文分词，过滤空白 token。"""
    return [t for t in jieba.lcut(text) if t.strip()]


def load_corpus(vs: Chroma) -> list[Document]:
    """把库里全部 chunk 读出来（BM25 需要在内存里建倒排索引）。

    量级说明：企业知识库场景 chunk 数在千级，全量载入内存完全可行；
    百万级才需要外置 BM25（如 Elasticsearch），那是另一个架构。
    """
    data = vs._collection.get(include=["documents", "metadatas"])
    return [
        Document(page_content=doc, metadata=meta or {})
        for doc, meta in zip(data["documents"], data["metadatas"])
    ]


def build_hybrid_retriever(vs: Chroma | None = None) -> BaseRetriever:
    """构建混合检索器：BM25 + 向量，加权 RRF 融合。

    可选 MultiQueryRetriever 包装（settings.enable_multi_query）：
    用 glm-4-flash 把问题改写成多个视角再检索，提升口语化提问的召回，
    代价是每次多一轮 LLM 调用，延迟敏感场景默认关。
    """
    vs = vs or get_vectorstore()
    corpus = load_corpus(vs)
    if not corpus:
        raise RuntimeError("知识库为空，先执行 ingest（python cli.py ingest）")

    bm25 = BM25Retriever.from_documents(corpus, preprocess_func=_tokenize_zh)
    bm25.k = settings.retrieve_k
    vector = vs.as_retriever(search_kwargs={"k": settings.retrieve_k})

    hybrid = EnsembleRetriever(
        retrievers=[bm25, vector],
        weights=[settings.bm25_weight, settings.vector_weight],
    )

    if settings.enable_multi_query:
        return MultiQueryRetriever.from_llm(
            retriever=hybrid,
            llm=get_chat_model(settings.rewrite_model),
        )
    return hybrid


class KBRetriever:
    """检索层门面：建一次索引，答多次问题（BM25 建索引有成本，不能每问重建）。

    mode 三档，对应评估阶段的消融对比：
        vector —— 纯向量（基线）
        hybrid —— BM25+向量混合
        rerank —— 混合 + 智谱重排（完整管线，默认）
    """

    MODES = ("vector", "hybrid", "rerank")

    def __init__(self, vs: Chroma | None = None):
        self.vs = vs or get_vectorstore()
        self.hybrid = build_hybrid_retriever(self.vs)

    def retrieve(self, question: str, mode: str | None = None) -> list[Document]:
        """按指定模式检索，返回 final_k 条带溯源 metadata 的材料。"""
        mode = mode or ("rerank" if settings.enable_rerank else "hybrid")
        if mode not in self.MODES:
            raise ValueError(f"未知检索模式 {mode!r}，可选：{self.MODES}")

        if mode == "vector":
            return self.vs.similarity_search(question, k=settings.final_k)

        candidates = self.hybrid.invoke(question)[: settings.retrieve_k]
        if mode == "hybrid":
            return candidates[: settings.final_k]
        return rerank_documents(question, candidates, top_n=settings.final_k)
