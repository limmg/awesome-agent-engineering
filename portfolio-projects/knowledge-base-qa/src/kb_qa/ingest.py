"""Ingest 管线：文档 → 分块 → 向量化 → Chroma 持久化（增量缓存）。

增量缓存（升级版 rag-09 模式）：
    rag-09 只做了「hash 相同就跳过」，但文件【修改】后旧块会残留在库里。
    这里补齐三种情况：
        新文件      → 全量入库
        文件被修改  → 先删旧块（按 source 过滤）再入库新块
        文件被删除  → prune 时清掉库里的孤儿块
    保证「库内容 == 目录内容」的最终一致，重复跑幂等。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.embeddings import ZhipuAIEmbeddings

from .config import settings
from .loader import file_md5, list_documents, load_and_split


def get_embeddings() -> ZhipuAIEmbeddings:
    if not settings.zhipuai_api_key:
        raise RuntimeError("未配置 ZHIPUAI_API_KEY（.env 或环境变量）")
    return ZhipuAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.zhipuai_api_key,
    )


def get_vectorstore() -> Chroma:
    """持久化 Chroma。cosine 距离（embedding-3 官方推荐），
    similarity_search 由 LangChain 统一处理 distance→score，不手算（rag-03 的坑）。
    """
    return Chroma(
        collection_name=settings.collection_name,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_path,
        collection_metadata={"hnsw:space": "cosine"},
    )


@dataclass(frozen=True)
class IngestReport:
    """一次 ingest 的结果统计（不可变，直接进日志/API 响应）。"""

    added_files: tuple[str, ...] = ()
    updated_files: tuple[str, ...] = ()
    skipped_files: tuple[str, ...] = ()
    pruned_files: tuple[str, ...] = ()
    added_chunks: int = 0
    total_chunks: int = 0


def _existing_hashes(vs: Chroma) -> dict[str, str]:
    """读出库里已有的 {source: src_hash} 映射（缓存判断依据）。"""
    data = vs._collection.get(include=["metadatas"])
    result: dict[str, str] = {}
    for meta in data.get("metadatas") or []:
        if meta and "source" in meta and "src_hash" in meta:
            result[meta["source"]] = meta["src_hash"]
    return result


def _add_in_batches(vs: Chroma, docs: list, ids: list[str]) -> None:
    """分批 add：智谱 embedding 单请求上限 64 条，超限直接 400。"""
    step = settings.embed_batch_size
    for i in range(0, len(docs), step):
        vs.add_documents(docs[i : i + step], ids=ids[i : i + step])


def ingest_directory(docs_dir: str | Path | None = None, prune: bool = True) -> IngestReport:
    """把目录下所有文档同步进向量库，返回统计报告。幂等：重复跑不产生变化。"""
    docs_dir = Path(docs_dir or settings.docs_dir)
    vs = get_vectorstore()
    existing = _existing_hashes(vs)

    files = list_documents(docs_dir)
    on_disk = {p.name for p in files}

    added: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    added_chunks = 0

    for path in files:
        fname = path.name
        fhash = file_md5(path)
        if existing.get(fname) == fhash:
            skipped.append(fname)
            continue

        is_update = fname in existing
        if is_update:
            # 文件改过：先清旧块，避免新旧版本混存
            vs._collection.delete(where={"source": fname})

        chunks = load_and_split(path)
        ids = [f"{fname}:{fhash[:8]}:{c.metadata['chunk_idx']}" for c in chunks]
        _add_in_batches(vs, chunks, ids)
        added_chunks += len(chunks)
        (updated if is_update else added).append(fname)

    # 目录里已删除的文件，库里的孤儿块一并清掉
    pruned: list[str] = []
    if prune:
        for fname in existing:
            if fname not in on_disk:
                vs._collection.delete(where={"source": fname})
                pruned.append(fname)

    return IngestReport(
        added_files=tuple(added),
        updated_files=tuple(updated),
        skipped_files=tuple(skipped),
        pruned_files=tuple(pruned),
        added_chunks=added_chunks,
        total_chunks=vs._collection.count(),
    )
