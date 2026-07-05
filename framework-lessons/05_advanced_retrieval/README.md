# Lesson 05 — 高级检索工程化：Ensemble + MultiQuery

> **本课定位**：LangChain 段（L01-L05）收官课。把你 RAG L06（混合检索）和 L07（Query 改写）手写的高级检索，用框架组件化——**这是框架真正省力的地方**：手写 RRF 融合、手写多查询展开，每段都是 20+ 行；用框架，一个对象搞定。
>
> **映射的手写课**：
> - `rag-lessons/06_advanced_retrieval`（手写 `BM25Okapi` + 手写 `rrf_fusion` + 手写 `lightweight_rerank`）
> - `rag-lessons/07_query_rewrite`（手写 HyDE + 手写多查询 `rrf_merge_multi`）

---

## 一、回顾：你手写混合检索有多费劲？

打开 `rag-lessons/06_advanced_retrieval/code.py`，你为了实现"向量 + BM25 混合检索"手写了：

1. `simple_tokenize()` —— 手写分词器（10 行）
2. `bm25_search()` —— 手写 BM25 调用（5 行）
3. `rrf_fusion()` —— **手写 RRF 融合公式**（12 行）：
   ```python
   for rank, (doc, _) in enumerate(vector_results, 1):
       scores[doc] += 1 / (k + rank)
   for rank, (doc, _) in enumerate(bm25_results, 1):
       scores[doc] += 1 / (k + rank)
   ```
4. 还有向量检索、结果合并、排序……

而 RAG L07 的多查询展开，你又**重写了一遍 RRF**（`rrf_merge_multi`），因为多路结果要融合。

**核心痛点**：每次想做"多路检索 + 融合"，都得手写一遍融合逻辑。

---

## 二、`EnsembleRetriever` —— 混合检索的组件化

LangChain 把"多路检索 + RRF 融合"封装成了一个对象：

```python
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever

# ① BM25 检索器（对应你手写的 bm25_search）
bm25 = BM25Retriever.from_documents(docs, k=3)

# ② 向量检索器（L04 学过的）
vs_retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# ③ 混合：EnsembleRetriever 自动做 RRF 融合！（对应你手写的 rrf_fusion）
ensemble = EnsembleRetriever(
    retrievers=[bm25, vs_retriever],
    weights=[0.5, 0.5],   # 两路权重
)
results = ensemble.invoke("问题")   # → 自动融合后的 List[Document]
```

**对比代码量**：

| 你手写（RAG L06） | 框架版 |
|---|---|
| `simple_tokenize`（10 行）| 不需要（BM25Retriever 内置分词）|
| `bm25_search`（5 行）| `BM25Retriever.from_documents()`（1 行）|
| `rrf_fusion`（12 行）| `EnsembleRetriever(retrievers=[...])`（1 行）|
| 手动合并两路结果 | 自动 |

**而且 `EnsembleRetriever` 本身是 Retriever**——它直接能接进 L04 的 RAG 链，一行替换：

```python
# L04 的链：
chain = {"context": retriever | format, ...} | prompt | llm | parser
# 把 retriever 从向量换成混合，链的其他部分不动：
retriever = EnsembleRetriever(retrievers=[bm25, vs_retriever])  # ← 只改这一行
```

这就是 L04 讲的"Retriever 抽象 = 可替换性"的真实威力。

> **原理没变**：EnsembleRetriever 内部用的就是 RRF（Reciprocal Rank Fusion），和你 RAG L06 手写的 `1/(k+rank)` 是同一个公式。框架只是把它封装好了。

---

## 三、`MultiQueryRetriever` —— Query 改写的组件化

RAG L07 你手写多查询展开，要：
1. 手写 prompt 让 LLM 拆子问题
2. 手写 `chat()` 调用
3. 手写每个子问题分别检索
4. 手写 `rrf_merge_multi` 融合

框架把这些全收进 `MultiQueryRetriever`：

```python
from langchain_classic.retrievers import MultiQueryRetriever

mq_retriever = MultiQueryRetriever.from_llm(
    retriever=vs_retriever,   # 基础向量检索器
    llm=llm,                  # 用 LLM 自动生成多个子查询
)
results = mq_retriever.invoke("我想歇几天，那个流程是啥？")
# 背后：LLM 自动生成 3 个子查询 → 分别检索 → RRF 融合 → 返回
```

**它自动做了**：
- 生成子查询的 prompt（不用你手写）
- 调用 LLM 拆问题
- 多路检索 + RRF 融合

对比你 RAG L07 手写了 `multi_prompt` + `chat()` + 循环检索 + `rrf_merge_multi`（约 30 行），这里 1 行。

> **原理没变**：还是你 RAG L07 学的"把一个问题展开成多个子问题，分别检索后融合"。MultiQueryRetriever 内部的融合用的也是 RRF。

---

## 四、⚠️ 一个必须讲清的现实：导入路径的迁移阵痛

本课你会发现一个**奇怪的现象**——三个检索器来自**不同的包**：

```python
from langchain_community.retrievers import BM25Retriever        # community 包
from langchain_classic.retrievers import EnsembleRetriever      # classic 包
from langchain_classic.retrievers import MultiQueryRetriever    # classic 包
```

### 为什么？

LangChain 1.x 重构时，把一些"经典"组件（agents、旧 retrievers、chains）挪到了 **`langchain_classic`** 包（一个过渡/兼容层）。`EnsembleRetriever` 和 `MultiQueryRetriever` 目前就在那里。

**这不是 bug，是真实的框架演进代价**：
- 你在用框架时，会反复遇到"这个类从哪导入"的问题
- 不同版本路径不同，Stack Overflow 的旧答案可能过时
- 这就是 L01 README 说的"框架的黑盒化 + 版本迁移成本"

**怎么应对**（实用技巧）：
1. 遇到 `ImportError`，先 `pip show langchain_classic` 看有没有这个包
2. 不确定路径时，用 `python -c "import langchain_community.retrievers as r; print(dir(r))"` 列出模块里有什么
3. 官方文档的" Integrations"页面会标注每个组件的当前包

> 这本身就是面试加分点：能说出"LangChain 1.x 把经典组件挪到了 langchain_classic，community 在 sunset"——说明你真的踩过这些坑，而不是纸上谈兵。

---

## 五、框架的边界：Rerank 仍需自行接入

你在 RAG L06 还手写了 `lightweight_rerank`（轻量重排序）。LangChain 有没有现成的 reranker？

**有，但需要额外组件**：
- `ContextualCompressionRetriever` + `LLMChainExtractor`：用 LLM 二次筛选（思路对，但不是真正的 cross-encoder）
- 真正的 cross-encoder reranker（如 bge-reranker）需要单独装 `langchain-cohere` / `FlagEmbedding` 等

**本课不演示 reranker**，原因和 RAG L06 一样：reranker 没有智谱官方的 LangChain 集成，接入要装第三方包，配置成本高。但这正是教学点：

> **框架不是万能的**。RAG 的"召回 + 精排两段式"里，召回（Ensemble/MultiQuery）框架封装得很好，但精排（reranker）往往要你自己接。理解这个边界，比会用 API 重要。

如果你需要 reranker，RAG L06 的手写思路完全适用——把 `lightweight_rerank` 换成真实的 cross-encoder 即可，流程不变。

---

## 六、本课代码

`code.py` 两个实验 + 一个边界讨论：

1. **EnsembleRetriever**：用 BM25+向量混合检索，召回带编号的文档（对应 RAG L06 的"向量翻车"场景）
2. **MultiQueryRetriever**：用口语化问题，LLM 自动拆子查询（对应 RAG L07）
3. **边界讨论**：对比代码量，并演示 reranker 需自行接入

---

## 七、LangChain 段收官小结（L01-L05）

学完本课，LangChain 段（RAG 工程化）全部完成。回顾你掌握的能力：

| 课 | 框架能力 | 对应手写课 |
|---|---------|----------|
| L01 | LCEL 管道（invoke/stream/batch）| RAG L01 |
| L02 | Models + Prompts + Parsers（结构化输出）| RAG L05、Agent L02 |
| L03 | Loaders + Splitters + VectorStores（Document 流水线）| RAG L03、L04 |
| L04 | Retrievers + RAG Chain（引用溯源、可替换）| RAG L01-L05 |
| L05 | Ensemble + MultiQuery（高级检索组件化）| RAG L06、L07 |

**核心认知**：框架把你手写的每一段逻辑都封装成了可组合、可替换的组件。原理你全懂（前两门课），框架是杠杆。但框架也有边界（版本迁移、reranker 需自接、黑盒化）——清醒地知道这些边界，才是高级工程师。

🔜 **L06 起**进入 **LangGraph 段**（Agent 工程化）：用 StateGraph 重写你 Agent L03 手写的 ReAct 循环——图结构、状态化、可持久化。这是 LangChain 官方推荐的 Agent 编排方式，也是 2024+ 生产级 Agent 的首选。
