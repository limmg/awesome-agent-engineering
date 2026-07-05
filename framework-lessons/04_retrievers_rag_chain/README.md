# Lesson 04 — Retrievers + RAG Chain

> **本课定位**：把 L01-L03 学的积木**全部串起来**，组装成一条完整的 RAG 链。这是 LangChain 段（L01-L05）的"合体"时刻——你会看到前三课的组件如何用 `|` 拼成生产级 RAG。
>
> **映射的手写课**：RAG L01-L05 的全部逻辑（检索 + 拼 prompt + 调模型 + 引用溯源）。你在 L01 已经组装过一条最简 RAG 链，本课在此基础上加上**引用溯源**（来源透传），并深入理解 Retriever 抽象的价值。

---

## 一、为什么需要 Retriever 抽象？

L03 你已经能把向量库当检索器用了：

```python
vectorstore = Chroma.from_documents(...)
results = vectorstore.similarity_search("问题", k=3)   # 直接调向量库
retriever = vectorstore.as_retriever()                  # 或转成 retriever
```

看起来 `similarity_search` 也能用，为什么要多此一举转成 Retriever？

### 答案：Retriever 统一了「所有检索方式」的接口

`VectorStoreRetriever` 只是 Retriever 的**一种实现**。LangChain 里还有很多别的：

| Retriever 类型 | 怎么检索 | 你手写过的对应物 |
|---------------|---------|----------------|
| `VectorStoreRetriever` | 向量相似度 | RAG L03（Chroma 向量检索）|
| `BM25Retriever` | 关键词匹配 | RAG L06（rank-bm25）|
| `EnsembleRetriever` | 向量+BM25 混合 | RAG L06（RRF 融合）|
| `MultiQueryRetriever` | 多查询展开 | RAG L07（多查询）|
| `ContextualCompressionRetriever` | 检索后二次压缩 | RAG L06（rerank 思路）|

**它们都实现同一个接口**：`.invoke(question)` → `List[Document]`。

这意味着：你的 RAG 链里写的是 `retriever`，换检索策略（向量→混合→多查询）**只改 retriever 这一个变量，链的其他部分一行不动**。

```python
chain = {"context": retriever | format, "question": ...} | prompt | llm | parser

# 换检索策略，只改这一行：
retriever = vectorstore.as_retriever()                    # 纯向量
retriever = EnsembleRetriever(retrievers=[vs_r, bm25_r])  # 混合（L05 会用）
retriever = MultiQueryRetriever(llm=llm, retriever=vs_r)  # 多查询（L05 会用）
# chain 本身完全不变！
```

对比你 RAG 课里：从 L03（向量）→ L06（混合）→ L07（多查询），每次换检索策略都得改调用代码。Retriever 抽象把这层差异抹平了——**这就是"工程化"的核心价值：解耦、可替换、可组合**。

### Retriever 是 Runnable

和 L02 的三件套一样，Retriever 也是 Runnable。所以它能用 `|` 接进 LCEL 链，自动获得 `invoke/stream/batch`。这是为什么 L01 的链能写成 `retriever | format | prompt | ...`。

---

## 二、回顾：L01 你组装过的最简 RAG 链

```python
chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt | llm | parser
)
answer = chain.invoke("问题")   # → 纯字符串
```

这条链做完了 RAG 的核心：检索 → 拼 prompt → 生成。但它有个缺陷——**只输出答案字符串，丢失了"来源信息"**。

你 RAG L05 手写引用溯源时，是把检索结果单独保存、再手动和答案配对。在 LCEL 里怎么优雅地做到"既输出答案、又输出来源"？

---

## 三、本课进阶：用 `.assign()` 实现来源透传（引用溯源）

这是本课的技术核心。先理解一个 LCEL 关键方法：

### `RunnablePassthrough.assign()` —— "保留原数据，再追加新字段"

`RunnablePassthrough` 本身是"原样透传"。`.assign(新字段=计算逻辑)` 的作用是：**保留输入的所有字段，再追加计算出的新字段**。

```python
# 输入：{"question": "..."}
RunnablePassthrough.assign(context=retriever | format_docs)
# 输出：{"question": "...", "context": "..."}   ← question 保留，context 追加
```

### 串成"带来源"的 RAG 链

```python
chain = (
    # 第 1 步：检索，得到 docs（保留原 question）
    RunnablePassthrough.assign(docs=get_question | retriever)
    # 第 2 步：把 docs 拼成 context 文本（保留 question + docs）
    .assign(context=lambda x: format_docs(x["docs"]))
    # 第 3 步：用 context+question 生成 answer（保留 question + docs + context）
    .assign(answer=prompt | llm | parser)
)
result = chain.invoke({"question": "..."})
# result = {"question": ..., "docs": [...], "context": ..., "answer": ...}
```

**结果是一个 dict，同时包含 `answer`（答案）和 `docs`（来源 Document 列表）**。这样你就能打印「答案 + 引用来源」，实现你 RAG L05 手写过的引用溯源——但在 LCEL 里，它是声明式的、可组合的。

> 对比你 RAG L05：手写时要 `retrieved = retrieve(...)` 单独存一份、`answer = chat(...)`、最后手动把两者配对打印。LCEL 用 `.assign()` 让数据"一路带着走"。

### `RunnableLambda` —— 把普通函数变成 Runnable

链里用到了 `get_question = RunnableLambda(lambda x: x["question"])`。

为什么需要它？因为 `retriever` 期望输入是字符串（问题），但链里流转的是 dict（`{"question": ...}`）。`RunnableLambda` 把"从 dict 取 question"这个普通函数包成 Runnable，就能用 `|` 串进管道。

> 记住这个规律：**LCEL 链里任何"自定义处理"都要用 `RunnableLambda` 包一下**，否则不能用 `|`。

---

## 四、完整 RAG 链：对照你的手写版

把 L01-L04 的组件全部拼起来，对照你 RAG L01+L05 手写的全流程：

| 你的手写步骤（RAG L01+L05）| LCEL 链里的对应环节 |
|---------------------------|-------------------|
| `retrieve()` 函数检索 | `retriever`（VectorStore 转的 Runnable）|
| 手拼 `f"【材料】\n{context}"` | `retriever | format_docs` + `ChatPromptTemplate` |
| `chat()` 调模型 | `llm`（ChatZhipuAI）|
| `response.choices[0].message.content` | `StrOutputParser()` |
| 手动保存 retrieved 做引用 | `.assign(docs=retriever)` 透传来源 |
| `chat_stream()` 流式 | `.stream()`（同一链，换方法）|

**一条 LCEL 链 = 你手写的全部逻辑，但声明式、可组合、自动支持 stream/batch。**

---

## 五、本课代码

`code.py` 三个部分：

1. **回顾最简 RAG 链**（L01 的链，加深理解）
2. **进阶：带引用溯源的 RAG 链**（用 `.assign()` 透传来源，对应 RAG L05）
3. **演示可替换性**：同一套 chain 代码，换 retriever 的 k 值验证"只改一处"

---

## 六、小结 & 下节预告

✅ 现在你应该明白：
- Retriever 抽象统一了所有检索方式的接口（换检索策略只改一处）
- `.assign()` 如何在链里"保留原数据 + 追加新字段"
- 如何用 LCEL 组装带引用溯源的完整 RAG 链
- 一条 LCEL 链如何对应你 RAG L01-L05 的全部手写逻辑

🔜 **L05**（LangChain 段最后一课）进入高级检索工程化：`EnsembleRetriever`（混合检索）+ `MultiQueryRetriever`（多查询展开），把你在 RAG L06/L07 手写的高级检索组件化——这是框架真正省力的地方。学完 L05，LangChain 段就收官了。
