# Lesson 05 练习 — 高级检索工程化（LangChain 段收官）

> 本课练习重点体会"框架把多路检索 + 融合封装成一个对象"的省力程度。

---

## 练习 1：对比混合检索代码量（核心认知，10 分钟）

打开 `rag-lessons/06_advanced_retrieval/code.py`，数一下你手写混合检索用了多少行（`simple_tokenize` + `bm25_search` + `rrf_fusion` + 调用）。

再数本课 `experiment_1_ensemble` 用了多少行（`BM25Retriever.from_documents` + `EnsembleRetriever(retrievers=...)`）。

把两个数字写下来。**这就是框架的价值量化**。

**思考**：省下来的代码，本质上是"重复造轮子"的部分。框架让你把精力放在调参和业务逻辑上。

---

## 练习 2：调 Ensemble 权重（5 分钟）

`experiment_1_ensemble` 里 `weights=[0.5, 0.5]`。试着调成：
- `[0.8, 0.2]`（偏 BM25）
- `[0.2, 0.8]`（偏向量）

用同一个带编号的查询（如 `FORM-A12`），观察正确答案的排名变化。

**思考**：这和你 RAG L06 练习"调整融合权重"是不是一回事？（原理没变，框架只是让调参更方便。）

---

## 练习 3：MultiQuery 换问题类型（10 分钟）

`experiment_2_multi_query` 用的是口语化问题。换成**正式但模糊**的问题试试：
- `"公司的休假申请需要什么前置条件？"`
- `"请假相关的表单和审批流程是什么？"`

观察：MultiQuery 生成的子查询质量如何？正式问题比口语化问题的提升幅度一样大吗？

**思考**：多查询改写在什么场景下收益最大？（提示：口语化、指代不明、多意图的问题。你 RAG L07 的发现在这里同样适用。）

---

## 练习 4：把高级检索器接进完整 RAG 链（综合，15 分钟）

这是本课最重要的练习——**验证 Retriever 可替换性**。

用 L04 的 RAG 链结构，把 retriever 分别换成：
1. 单向量 retriever（L04 的基线）
2. EnsembleRetriever（本课实验①）
3. MultiQueryRetriever（本课实验②）

同一个问题，对比三种的最终答案质量。

```python
# 复用 L04 的链工厂
def make_chain(retriever, llm, prompt):
    return (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt | llm | StrOutputParser()
    )

# 三种 retriever，同一个 make_chain
for name, ret in [("向量", vs_r), ("混合", ensemble), ("多查询", mq)]:
    chain = make_chain(ret, llm, prompt)
    print(f"{name}: {chain.invoke('FORM-A12怎么用')[:60]}")
```

**观察**：
- 链的代码（`make_chain`）三种都一样，只换 retriever ✅
- 哪种检索器的答案最准？（带编号的问题，混合/多查询应该更好）

> 这就是 L04 讲的"Retriever 抽象 = 可替换性"的实战验证。你 RAG 课里从 L03→L06→L07 每次换检索都要改代码，框架里只改一个变量。

---

## 练习 5：手写 Rerank 接入（进阶，可选，15 分钟）

RAG L06 你手写过 `lightweight_rerank`。试着把它包装成一个能接进 LCEL 链的组件：

```python
from langchain_core.runnables import RunnableLambda

def rerank_docs(query_and_docs):
    """接收 {question, docs}，返回 rerank 后的 docs。"""
    query = query_and_docs["question"]
    docs = query_and_docs["docs"]
    # 复用 RAG L06 的 lightweight_rerank 逻辑
    ...
    return {"question": query, "docs": reranked}

rerank_step = RunnableLambda(rerank_docs)
# 接进链：retriever → rerank → prompt
```

**思考**：为什么 reranker 没有像 EnsembleRetriever 那样的现成组件？（提示：reranker 强依赖具体模型，各家实现差异大，难统一封装。）

---

## 思考题（不写代码）

1. **EnsembleRetriever 内部用的是什么融合算法？** 回顾你 RAG L06 手写的 `rrf_fusion`，公式是什么？框架封装后原理变了吗？

2. **为什么 EnsembleRetriever 在 `langchain_classic` 而 BM25Retriever 在 `langchain_community`？** 这反映了 LangChain 1.x 的什么变化？（提示：L01/L05 README 的迁移背景）

3. **框架封装了混合检索和多查询，但没封装 reranker。** 这说明框架的设计取舍是什么？（提示：通用性 vs 专一性）

---

## 完成标志

- [ ] 跑通 EnsembleRetriever，对比手写 RRF 的代码量
- [ ] 跑通 MultiQueryRetriever，理解它自动生成子查询
- [ ] 把高级检索器接进 L04 的 RAG 链，验证可替换性（练习 4）
- [ ] 理解 reranker 是框架的边界，需自行接入

🎉 **LangChain 段（L01-L05）全部完成！** 下一课 [L06](../06_langgraph_basics/) 进入 LangGraph 段：用 StateGraph 重写你 Agent L03 的 ReAct 循环。
