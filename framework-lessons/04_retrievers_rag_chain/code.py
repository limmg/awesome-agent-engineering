"""
Lesson 04 — Retrievers + RAG Chain
===================================
把 L01-L03 的积木组装成完整 RAG 链。本课在 L01 最简链基础上加：
    ① 回顾最简 RAG 链
    ② 进阶：带引用溯源的 RAG 链（用 .assign() 透传来源，对应 RAG L05）
    ③ 演示可替换性（换 retriever 的 k 值，链代码不变）

映射：rag-lessons/01_getting_started ~ 05_prompt 的全部逻辑

运行：python framework-lessons/04_retrievers_rag_chain/code.py
"""
# 消除 langchain-community 的 sunset 警告（L01 README 已讲过背景）
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")

import os

try:  # 兼容旧 Python 的 sqlite3（3.9+ 可忽略）
    import pysqlite3
    import sys
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

from dotenv import load_dotenv

# === LangChain 组件（L01-L03 学过的，这里全部串起来）===
from langchain_community.chat_models import ChatZhipuAI
from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.document_loaders import TextLoader
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda

EMBEDDING_MODEL = "embedding-3"
CHAT_MODEL = "glm-4"          # 想免费可换 "glm-4-flash"
COLLECTION_NAME = "acme_handbook_l04"
CHROMA_PATH = "./chroma_db_l04"

DOC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "sample_docs", "employee_handbook.md"
)

QUESTION = "我工作 4 年了，能休几天年假？报销截止日期是多久？"


# ════════════════════════════════════════════════════════════
# 准备：建知识库（load → split → store，L03 的完整流水线）
# ════════════════════════════════════════════════════════════
def build_knowledge_base():
    """复用 L03 的流水线：TextLoader → split_documents → Chroma.from_documents。

    这就是 L03 学的：一行 load、一行 split、一行 store。
    """
    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")

    embeddings = ZhipuAIEmbeddings(model=EMBEDDING_MODEL, api_key=api_key)

    # load（L03 实验①）
    docs = TextLoader(DOC_PATH, encoding="utf-8").load()
    # split（L03 实验②）—— metadata 自动透传
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=300, chunk_overlap=50,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    ).split_documents(docs)
    # store（L03 实验③）—— 一行入库
    vectorstore = Chroma.from_documents(
        chunks, embeddings,
        collection_name=COLLECTION_NAME, persist_directory=CHROMA_PATH,
    )
    print(f"✅ 知识库就绪：{len(chunks)} 个 chunk 已入库")
    return vectorstore, api_key


def format_docs(docs):
    """把 List[Document] 拼成一段文本（给 prompt 用）。

    对比 RAG L05 手写：context = '\n\n'.join(f'【材料{i+1}】{doc}' for ...)
    """
    return "\n\n".join(f"【材料{i+1}】{d.page_content}" for i, d in enumerate(docs))


# ════════════════════════════════════════════════════════════
# 部分①：回顾最简 RAG 链（L01 的链）
# ════════════════════════════════════════════════════════════
def part_1_simple_chain(vectorstore, api_key):
    """L01 组装过的最简 RAG 链：retriever | prompt | llm | parser。

    对照手写（RAG L01 main）：
      retrieved = retrieve(client, collection, QUESTION)      # 检索
      answer = generate_answer(client, QUESTION, retrieved)  # 拼 prompt + 调模型
    LCEL 版用 | 串成声明式管道。
    """
    print("\n" + "═" * 64)
    print("部分①：最简 RAG 链（回顾 L01）")
    print("═" * 64)

    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    prompt = ChatPromptTemplate.from_template(
        "你是严谨的问答助手，只依据材料回答，没有就说不知道。\n"
        "【材料】\n{context}\n\n【问题】{question}"
    )
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt | llm | StrOutputParser()
    )
    answer = chain.invoke(QUESTION)
    print(f"\n问题：{QUESTION}")
    print(f"🤖 答案：{answer}")
    print("\n👉 这条链只输出答案字符串，丢失了'答案来自哪些材料'的信息。")
    print("   下面部分②解决这个缺陷——加入引用溯源。")


# ════════════════════════════════════════════════════════════
# 部分②：进阶——带引用溯源的 RAG 链（对应 RAG L05）
# ════════════════════════════════════════════════════════════
def part_2_chain_with_sources(vectorstore, api_key):
    """用 .assign() 让检索来源一路透传到输出，实现引用溯源。

    核心：RunnablePassthrough.assign(新字段=计算) —— 保留原字段，追加新字段。
    这样最终的输出 dict 同时含 answer（答案）和 docs（来源 Document）。
    """
    print("\n" + "═" * 64)
    print("部分②：带引用溯源的 RAG 链（.assign 透传来源）")
    print("═" * 64)

    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是严谨的问答助手。只依据材料回答，没有就说不知道。用【材料N】标注引用。"),
        ("human", "【材料】\n{context}\n\n【问题】{question}"),
    ])
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)

    # RunnableLambda：把普通函数包成 Runnable，才能用 | 串进管道
    get_question = RunnableLambda(lambda x: x["question"])

    # ⭐ 核心链：三层 assign，数据一路带着走
    chain = (
        # 第 1 层：检索 docs（输入 {question} → 输出 {question, docs}）
        RunnablePassthrough.assign(docs=get_question | retriever)
        # 第 2 层：docs 拼成 context 文本（→ {question, docs, context}）
        .assign(context=lambda x: format_docs(x["docs"]))
        # 第 3 层：生成 answer（→ {question, docs, context, answer}）
        .assign(answer=prompt | llm | StrOutputParser())
    )

    result = chain.invoke({"question": QUESTION})

    print(f"\n问题：{QUESTION}")
    print(f"\n🤖 答案：\n{result['answer']}")

    print(f"\n📎 引用来源（{len(result['docs'])} 条材料）：")
    for i, d in enumerate(result["docs"], 1):
        preview = d.page_content.replace("\n", " ")[:50]
        source = d.metadata.get("source", "?")
        # 只取文件名，路径太长
        fname = os.path.basename(source) if isinstance(source, str) else "?"
        print(f"  【材料{i}】({fname}) {preview}...")

    print("\n👉 对比 RAG L05 手写引用溯源：")
    print("   手写要单独存 retrieved、再和 answer 手动配对打印。")
    print("   LCEL 用 .assign() 让 docs 一路透传，输出 dict 同时含 answer + docs。")
    print("   ⭐ answer 和 sources 是同一次检索的结果，天然对应，不会错位。")


# ════════════════════════════════════════════════════════════
# 部分③：演示可替换性（Retriever 抽象的价值）
# ════════════════════════════════════════════════════════════
def part_3_swappable_retriever(vectorstore, api_key):
    """同一套 chain 代码，只改 retriever 的 k 值，验证'换检索策略只改一处'。

    这里用 k=2 vs k=5 演示（L05 会换成真正的不同 Retriever 类型）。
    """
    print("\n" + "═" * 64)
    print("部分③：可替换性演示（换 retriever 的 k，链代码不变）")
    print("═" * 64)

    prompt = ChatPromptTemplate.from_template(
        "依据材料回答：{context}\n问题：{question}"
    )
    llm = ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)
    simple_q = "试用期员工能远程办公吗？"

    # 同一条链的工厂函数 —— 只接收 retriever
    def make_chain(retriever):
        return (
            {"context": retriever | format_docs, "question": RunnablePassthrough()}
            | prompt | llm | StrOutputParser()
        )

    for k in [2, 5]:
        # ⭐ 只改这一行：retriever 的参数
        retriever = vectorstore.as_retriever(search_kwargs={"k": k})
        chain = make_chain(retriever)   # 链的代码完全一样
        answer = chain.invoke(simple_q)
        print(f"\n[k={k}] 问题：{simple_q}")
        print(f"  答案：{answer[:70]}...")

    print("\n👉 观察：k=2 和 k=5 给模型的材料数量不同，答案详略可能不同。")
    print("   ⭐ 关键认知：换 retriever 参数（甚至 L05 换成 EnsembleRetriever），")
    print("      chain 的代码一行都不用改——这就是 Retriever 统一接口的价值。")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 04 — Retrievers + RAG Chain（组装完整 RAG）")
    print("=" * 64)
    print("把 L01-L03 的积木串成完整 RAG 链，加入引用溯源。")
    print("映射：rag-lessons/01 ~ 05 的全部逻辑")

    vectorstore, api_key = build_knowledge_base()

    part_1_simple_chain(vectorstore, api_key)             # 回顾最简链
    part_2_chain_with_sources(vectorstore, api_key)       # 带引用溯源
    part_3_swappable_retriever(vectorstore, api_key)      # 可替换性

    print("\n" + "=" * 64)
    print("✅ RAG Chain 小结：")
    print("   - Retriever 统一了所有检索方式（换策略只改 retriever 一处）")
    print("   - .assign() 让来源 docs 一路透传，实现引用溯源")
    print("   - 一条 LCEL 链 = RAG L01-L05 的全部手写逻辑（声明式、可 stream/batch）")
    print("=" * 64)


if __name__ == "__main__":
    main()
