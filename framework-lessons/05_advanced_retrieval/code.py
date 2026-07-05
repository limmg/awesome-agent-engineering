"""
Lesson 05 — 高级检索工程化：Ensemble + MultiQuery
===================================================
LangChain 段收官课。把 RAG L06（混合检索）和 L07（Query 改写）组件化。

两个实验 + 边界讨论：
  ① EnsembleRetriever：BM25 + 向量 混合检索（对应 RAG L06 手写 RRF）
  ② MultiQueryRetriever：LLM 自动拆子查询（对应 RAG L07 手写多查询）
  ③ 边界讨论：reranker 仍需自行接入（框架不万能）

⚠️ 导入路径注意（L05 README 详解）：
  - BM25Retriever 在 langchain_community
  - EnsembleRetriever / MultiQueryRetriever 在 langchain_classic（1.x 重构迁移）

运行：python framework-lessons/05_advanced_retrieval/code.py
"""
# 消除各类 sunset/deprecation 警告（背景见各课 README）
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("langchain_classic").setLevel(logging.WARNING)

import os

try:  # 兼容旧 Python 的 sqlite3
    import pysqlite3
    import sys
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

from dotenv import load_dotenv

# === 检索器导入（注意三个不同包！）===
from langchain_community.retrievers import BM25Retriever            # BM25（community 包）
from langchain_classic.retrievers import EnsembleRetriever          # 混合（classic 包）
from langchain_classic.retrievers import MultiQueryRetriever        # 多查询（classic 包）

from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

EMBEDDING_MODEL = "embedding-3"
COLLECTION_NAME = "acme_l05_docs"
CHROMA_PATH = "./chroma_db_l05"

# 复用 RAG L06 的文档集：故意混入带编号/专有名词的，制造向量检索翻车场景
DOCUMENTS = [
    # 语义类（向量检索擅长）
    "员工入职满一年享有带薪年假福利，工龄越长假期越多。",
    "公司每年提供免费体检，覆盖所有正式员工。",
    "出差住宿费用可以申请报销，需要保留发票。",
    # 编号/专有名词类（BM25 擅长，向量检索容易漏）
    "表单 FORM-A12 用于申请年假，需在 OA 系统提交并附工号。",
    "故障码 ERR_0x42 表示网络连接超时，请检查防火墙配置。",
    "产品型号 PRJ-B200 的保修期为 24 个月，联系售后 8001。",
    # 干扰项
    "年假天数根据职级确定，经理级及以上额外增加 3 天。",
]


def create_embeddings():
    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    return ZhipuAIEmbeddings(model=EMBEDDING_MODEL, api_key=api_key), api_key


def show_results(label, docs, correct_keyword="FORM-A12"):
    """打印检索结果，标记正确答案（含 FORM-A12 的那条）。"""
    print(f"\n【{label}】Top-{len(docs)}：")
    for i, d in enumerate(docs, 1):
        mark = " ✅正确" if correct_keyword in d.page_content else ""
        print(f"  {i}. {d.page_content[:40]}...{mark}")
    hit = sum(1 for d in docs if correct_keyword in d.page_content)
    print(f"  → 正确答案 {hit}/1 在结果中")


# ════════════════════════════════════════════════════════════
# 准备：建 BM25 + 向量 两个基础检索器
# ════════════════════════════════════════════════════════════
def build_base_retrievers(embeddings):
    """建两个基础检索器，供 Ensemble 组合。

    对照 RAG L06 手写：你要手写 simple_tokenize + bm25_search + 向量检索 + rrf_fusion。
    这里 BM25Retriever 和 Chroma.as_retriever 各一行。
    """
    docs = [Document(page_content=t) for t in DOCUMENTS]

    # ① BM25 检索器（对应手写 bm25_search，内置分词，不用手写 simple_tokenize）
    bm25 = BM25Retriever.from_documents(docs, k=3)

    # ② 向量检索器（L04 学过的）
    vs = Chroma.from_documents(
        docs, embeddings,
        collection_name=COLLECTION_NAME, persist_directory=CHROMA_PATH,
    )
    vs_retriever = vs.as_retriever(search_kwargs={"k": 3})
    return bm25, vs_retriever


# ════════════════════════════════════════════════════════════
# 实验①：EnsembleRetriever —— 混合检索（对应 RAG L06）
# ════════════════════════════════════════════════════════════
def experiment_1_ensemble(bm25, vs_retriever):
    """BM25 + 向量 混合检索，自动 RRF 融合。

    对照 RAG L06 手写 rrf_fusion（12 行公式）：
        for rank, (doc,_) in enumerate(vector_results, 1):
            scores[doc] += 1/(k+rank)
        ...
    框架版：EnsembleRetriever 自动做 RRF。
    """
    print("\n" + "═" * 64)
    print("实验①：EnsembleRetriever —— BM25 + 向量 混合检索")
    print("═" * 64)

    query = "表单 FORM-A12 怎么填？需要附什么信息？"
    print(f"\n查询：{query}")
    print(f"（正确答案：含 FORM-A12 的那条文档）")

    # 先看单路效果（对照）
    print("\n--- 单路对照 ---")
    show_results("单 BM25", bm25.invoke(query))
    show_results("单 向量", vs_retriever.invoke(query))

    # ⭐ Ensemble 自动 RRF 融合
    ensemble = EnsembleRetriever(
        retrievers=[bm25, vs_retriever],
        weights=[0.5, 0.5],   # 两路权重，可调
    )
    print("\n--- 混合检索（自动 RRF 融合）---")
    show_results("Ensemble 混合", ensemble.invoke(query))

    print("\n👉 对比 RAG L06 手写：")
    print("   手写要 simple_tokenize + bm25_search + rrf_fusion（共 ~30 行）")
    print("   框架版 EnsembleRetriever(retrievers=[...]) 一行，内部自动 RRF。")
    print("   ⭐ 它是 Retriever，直接能替换进 L04 的 RAG 链（链代码不变）。")


# ════════════════════════════════════════════════════════════
# 实验②：MultiQueryRetriever —— Query 改写（对应 RAG L07）
# ════════════════════════════════════════════════════════════
def experiment_2_multi_query(vs_retriever, api_key):
    """LLM 自动生成多个子查询，分别检索后 RRF 融合。

    对照 RAG L07 手写（约 30 行）：
        1. 手写 multi_prompt 让 LLM 拆问题
        2. 手写 chat() 调用
        3. 循环每个子问题检索
        4. 手写 rrf_merge_multi 融合
    框架版：MultiQueryRetriever.from_llm() 一行。
    """
    print("\n" + "═" * 64)
    print("实验②：MultiQueryRetriever —— LLM 自动拆子查询")
    print("═" * 64)

    from langchain_community.chat_models import ChatZhipuAI
    llm = ChatZhipuAI(model="glm-4-flash", api_key=api_key)  # 多查询用 flash 省钱

    # 口语化烂问题（和 RAG L07 一样的场景）
    query = "我想歇几天，那个流程是啥？要啥材料不？"
    print(f"\n查询（口语化）：{query}")

    print("\n--- 单向量检索（基线）---")
    show_results("单 向量", vs_retriever.invoke(query), correct_keyword="年假")

    # ⭐ MultiQuery 自动：生成子查询 → 分别检索 → RRF 融合
    mq = MultiQueryRetriever.from_llm(retriever=vs_retriever, llm=llm)
    print("\n--- MultiQuery（LLM 自动拆子查询 + 融合）---")
    show_results("MultiQuery", mq.invoke(query), correct_keyword="年假")

    print("\n👉 对比 RAG L07 手写：")
    print("   手写要 multi_prompt + chat + 循环检索 + rrf_merge_multi（~30 行）")
    print("   框架版 MultiQueryRetriever.from_llm() 一行，内部自动完成全流程。")
    print("   （LLM 会自动生成 3 个子查询，详见 DEBUG 日志——这里已静默。）")


# ════════════════════════════════════════════════════════════
# 边界讨论：Rerank 仍需自行接入
# ════════════════════════════════════════════════════════════
def section_rerank_boundary():
    """框架不是万能的：reranker 没有智谱官方集成，需自行接入。

    回顾 RAG L06 的 lightweight_rerank 思路：召回（Ensemble）+ 精排（rerank）。
    """
    print("\n" + "═" * 64)
    print("边界讨论：Rerank（框架不万能的地方）")
    print("═" * 64)
    print("""
你在 RAG L06 手写了 lightweight_rerank（精排）。LangChain 有现成的吗？

  ✓ ContextualCompressionRetriever + LLMChainExtractor
    → 用 LLM 二次筛选（思路对，但不是真正的 cross-encoder，慢且贵）
  ✗ 真正的 cross-encoder（bge-reranker / 智谱 reranker）
    → 需单独装第三方包，无智谱官方 LangChain 集成

结论：RAG 的"召回+精排两段式"里：
  - 召回（Ensemble/MultiQuery）框架封装得很好 ✅
  - 精排（reranker）往往要你自己接 ⚠️

这本身就是教学点：理解框架的边界，比会用 API 重要。
需要 reranker 时，RAG L06 的手写思路完全适用——
把 lightweight_rerank 换成真实 cross-encoder 即可，流程不变。
""")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 05 — 高级检索工程化（LangChain 段收官）")
    print("=" * 64)
    print("把 RAG L06（混合检索）+ L07（Query改写）组件化。")

    embeddings, api_key = create_embeddings()
    bm25, vs_retriever = build_base_retrievers(embeddings)
    print(f"✅ {len(DOCUMENTS)} 篇文档已就绪（BM25 + 向量 双检索器）")

    experiment_1_ensemble(bm25, vs_retriever)        # 混合检索
    experiment_2_multi_query(vs_retriever, api_key)  # 多查询
    section_rerank_boundary()                        # 边界讨论

    print("=" * 64)
    print("✅ LangChain 段（L01-L05）全部完成！回顾：")
    print("   L01 LCEL管道 | L02 三件套 | L03 数据层 | L04 RAG链 | L05 高级检索")
    print("下一阶段 L06 起：LangGraph 段（Agent 工程化，StateGraph 重写 ReAct）")
    print("=" * 64)


if __name__ == "__main__":
    main()
