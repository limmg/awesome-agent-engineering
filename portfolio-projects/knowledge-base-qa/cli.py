"""CLI：阶段验证入口。

用法（在项目根 portfolio-projects/knowledge-base-qa/ 下）：
    python cli.py ingest                 # 目录文档同步入库（增量）
    python cli.py query "试用期多久"     # 向量召回验证（阶段 1 仅裸检索）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# Windows 控制台默认 GBK，中文/emoji 输出会崩
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from kb_qa.config import settings  # noqa: E402
from kb_qa.ingest import get_vectorstore, ingest_directory  # noqa: E402


def cmd_ingest(args: argparse.Namespace) -> None:
    report = ingest_directory(prune=not args.no_prune)
    print(f"📂 目录：{settings.docs_dir}")
    if report.added_files:
        print(f"✅ 新增 {len(report.added_files)} 个文件：{', '.join(report.added_files)}")
    if report.updated_files:
        print(f"🔄 更新 {len(report.updated_files)} 个文件：{', '.join(report.updated_files)}")
    if report.skipped_files:
        print(f"♻️  跳过 {len(report.skipped_files)} 个未改动文件（命中缓存）")
    if report.pruned_files:
        print(f"🗑️  清理 {len(report.pruned_files)} 个已删除文件的孤儿块：{', '.join(report.pruned_files)}")
    print(f"📚 本次入库 {report.added_chunks} 块，知识库现有 {report.total_chunks} 块")


def cmd_query(args: argparse.Namespace) -> None:
    vs = get_vectorstore()
    results = vs.similarity_search_with_relevance_scores(args.question, k=args.k)
    if not results:
        print("（没有召回结果，先跑 python cli.py ingest）")
        return
    print(f"🔎 「{args.question}」 top-{args.k} 召回：\n")
    for i, (doc, score) in enumerate(results, 1):
        src = doc.metadata.get("source", "?")
        section = doc.metadata.get("section", "")
        loc = f"{src}::{section}" if section else src
        preview = doc.page_content.replace("\n", " ")[:80]
        print(f"[{i}] score={score:.4f}  {loc}")
        print(f"    {preview}...\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="企业知识库问答系统 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="同步文档目录到向量库（增量）")
    p_ingest.add_argument("--no-prune", action="store_true", help="不清理已删除文件的孤儿块")
    p_ingest.set_defaults(func=cmd_ingest)

    p_query = sub.add_parser("query", help="向量召回验证")
    p_query.add_argument("question", help="查询问题")
    p_query.add_argument("-k", type=int, default=4, help="召回条数（默认 4）")
    p_query.set_defaults(func=cmd_query)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
