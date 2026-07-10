"""智谱 reranker：cross-encoder 真重排。

为什么需要 rerank（rag-06 的玩具 token 命中率补成生产版）：
    混合召回（BM25+向量）解决「找得到」，但排序是两路分数线性融合的近似；
    cross-encoder 把 query 和每条候选拼在一起过模型，逐对精算相关性，
    排序质量显著高于 bi-encoder 的向量距离——代价是多一次 API 调用，
    所以只对召回后的少量候选（~8 条）重排，而不是全库。

可开关（settings.enable_rerank）：评估阶段跑「有/无 rerank」的
ragas context_precision 对比，量化 reranker 的价值。
"""
from __future__ import annotations

import logging

import httpx
from langchain_core.documents import Document

from .config import settings

logger = logging.getLogger(__name__)

_RERANK_URL = "https://open.bigmodel.cn/api/paas/v4/rerank"
_TIMEOUT_SECONDS = 15.0


def rerank_documents(
    query: str,
    docs: list[Document],
    top_n: int | None = None,
) -> list[Document]:
    """用智谱 rerank API 对候选文档重排，返回 top_n 条（带 rerank_score）。

    降级策略：rerank 是锦上添花，API 失败不应让整个问答挂掉——
    记 warning 后按原序截断返回（等价于关闭 rerank）。
    """
    top_n = top_n or settings.final_k
    if not docs:
        return []
    if len(docs) <= 1:
        return docs[:top_n]

    try:
        resp = httpx.post(
            _RERANK_URL,
            headers={"Authorization": f"Bearer {settings.zhipuai_api_key}"},
            json={
                "model": settings.rerank_model,
                "query": query,
                "documents": [d.page_content for d in docs],
                "top_n": len(docs),  # 全量要分数，top_n 截断放在本地做（见排序说明）
            },
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        results = resp.json()["results"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.warning("rerank 调用失败，降级为原序截断：%s", e)
        return docs[:top_n]

    # 实测坑：智谱 rerank 对「都挺相关」的候选分数饱和（多条精确 =1.0），
    # 同分时 API 返回顺序不稳定，会把混合检索排好的头部结果打乱。
    # 解法：本地按 (分数降序, 上游排名升序) 排——rerank 只在真有区分度时改变顺序，
    # 同分退回混合检索的排序（BM25+向量融合本身就是不错的先验）。
    ordered = sorted(results, key=lambda r: (-r["relevance_score"], r["index"]))[:top_n]

    # 不可变：不改原 Document，构造新对象带上 rerank_score
    return [
        Document(
            page_content=docs[r["index"]].page_content,
            metadata={**docs[r["index"]].metadata, "rerank_score": r["relevance_score"]},
        )
        for r in ordered
    ]
