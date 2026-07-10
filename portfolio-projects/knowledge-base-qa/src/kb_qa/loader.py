"""文档加载与结构感知分块。

为什么不用 rag-09 的纯 RecursiveCharacterTextSplitter：
    企业制度文档是强结构的（章节/条款），按字符数硬切会把「标题」和「正文」
    切散，检索命中一个孤零零的条款却丢了它属于哪一章。
    MarkdownHeaderTextSplitter 先按标题切出带层级 metadata 的节，
    再对超长的节用 RecursiveCharacterTextSplitter 二次切分兜底——
    每个 chunk 都自带 h1/h2/h3 上下文，引用溯源时能给出精确出处。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from .config import settings

SUPPORTED_SUFFIXES = (".md", ".txt")

_HEADERS_TO_SPLIT_ON = [("#", "h1"), ("##", "h2"), ("###", "h3")]


def file_md5(path: Path) -> str:
    """文件内容 MD5，作为增量缓存依据（复用 rag-09 的 src_hash 模式）。"""
    return hashlib.md5(path.read_bytes()).hexdigest()


def list_documents(docs_dir: str | Path) -> list[Path]:
    """扫描目录下所有受支持的文档，按文件名排序保证幂等。"""
    root = Path(docs_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"文档目录不存在：{root}")
    return sorted(p for p in root.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)


def _breadcrumb(meta: dict) -> str:
    """把标题层级拼成面包屑，如「员工手册 > 考勤管理 > 迟到处理」。"""
    parts = [meta.get(k) for k in ("h1", "h2", "h3")]
    return " > ".join(p for p in parts if p)


def split_markdown(text: str) -> list[Document]:
    """结构感知分块：先按标题切节，超长节再按字符二次切分。"""
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON,
        strip_headers=False,  # 保留标题在正文里，embedding 能吃到章节语义
    )
    sections = header_splitter.split_text(text)

    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    return size_splitter.split_documents(sections)


def split_plain_text(text: str) -> list[Document]:
    """无结构文本（.txt）退化为纯字符分块。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    return [Document(page_content=t) for t in splitter.split_text(text)]


def load_and_split(path: Path) -> list[Document]:
    """加载单个文档并分块，为每个 chunk 打上溯源 metadata。

    metadata 约定（检索层/生成层依赖）：
        source    —— 文件名，引用溯源展示用
        section   —— 标题面包屑，精确到条款的出处
        src_hash  —— 文件内容 MD5，增量缓存判断依据
        chunk_idx —— 块序号，稳定 id 生成用
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".md":
        chunks = split_markdown(text)
    else:
        chunks = split_plain_text(text)

    fhash = file_md5(path)
    return [
        Document(
            page_content=c.page_content,
            metadata={
                "source": path.name,
                "section": _breadcrumb(c.metadata),
                "src_hash": fhash,
                "chunk_idx": i,
            },
        )
        for i, c in enumerate(chunks)
    ]
