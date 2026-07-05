# Lesson 04 练习 — Retrievers + RAG Chain

> 本课把前 3 课的积木拼成完整 RAG。重点在第 2、3 题。

---

## 练习 1：理解 `.assign()` 的数据流（关键概念，10 分钟）

`part_2_chain_with_sources` 的链是三层 `.assign()`。回答：

1. 最外层 `chain.invoke({"question": "..."})` 输入是什么？最终输出的 dict 有几个 key？分别是什么？
2. 如果删掉中间那层 `.assign(context=...)`，直接把 `docs` 给 prompt，会怎样？（prompt 模板的 `{context}` 期望什么类型？）
3. 为什么 `get_question` 要用 `RunnableLambda` 包？直接写 `lambda x: x["question"]` 能用 `|` 串吗？试一下。

> 把答案写笔记里。理解 `.assign()` 的"保留+追加"语义 = 掌握 LCEL 进阶的钥匙。

---

## 练习 2：改 prompt 提升引用质量（10 分钟）

`part_2` 的 prompt 要求"用【材料N】标注引用"。试试两种 prompt 对比：

- **弱 prompt**：`"依据材料回答：{context}\n问题：{question}"`（不要求标注来源）
- **强 prompt**（当前）：要求"用【材料N】标注每条信息的来源"

用同一个问题跑两次，观察答案里是否出现 `【材料1】` 这样的标注。

**思考**：这和你 RAG L05 学的"防幻觉 prompt vs 无约束 prompt"是不是同一个原理？（提示：prompt 工程的原理在框架里完全适用——框架不改变原理。）

---

## 练习 3：给 RAG 链加流式输出（衔接 L01，5 分钟）

`part_2` 的链用了 `.assign(answer=prompt | llm | StrOutputParser())`。如果想**流式**输出 answer，难点在于：`.assign()` 默认等子链完整返回。

一个解法：把 answer 部分单独拿出来 stream。试着改写：先用链算出 `docs` 和 `context`（非 answer 部分），再单独对 `prompt | llm | StrOutputParser()` 调 `.stream()`。

提示：
```python
# 先跑到 context 这层
pre = chain_until_context.invoke({"question": q})
# 再单独流式 answer
for chunk in (prompt | llm | StrOutputParser()).stream(pre):
    print(chunk, end="", flush=True)
```

**思考**：为什么"完整链 + 流式 answer"比"分开两步"更难？这是 LCEL 流式的一个边界——L05 之后用 LangGraph 能更优雅地解决。

---

## 练习 4：验证可替换性（核心认知，10 分钟）

`part_3` 演示了换 `k` 值。现在做一个更接近真实的替换：

1. 用 `it_policy.md`（`data/sample_docs/it_policy.md`，你在 RAG L09 创建过）**再建一个 vectorstore**
2. 把 `part_3` 的 retriever 从"员工手册的"换成"IT 政策的"
3. 问一个 IT 相关问题（如"密码多久换一次？"）

**观察**：`make_chain` 函数的代码一行没改，只是传入了不同的 retriever——这就是可替换性。

> 进阶思考：L05 会把 retriever 换成完全不同的**类型**（EnsembleRetriever 混合检索），chain 代码仍然不变。这就是 Retriever 抽象的威力。

---

## 思考题（不写代码）

1. **Retriever 抽象和 VectorStore 有什么区别？** 既然 `vectorstore.similarity_search()` 也能检索，为什么还要 `as_retriever()`？（提示：统一接口、可替换、能接 LCEL）

2. **`.assign()` 解决了什么问题？** 如果没有它，想在链的输出里同时保留 answer 和 sources，你会怎么写？（对比手写的痛点）

3. **一条 LCEL RAG 链，对应你 RAG 课的哪几课？** 试着把链的每个环节映射到 RAG L01-L05 的具体函数。

---

## 完成标志

- [ ] 能口述 `.assign()` 的"保留+追加"语义
- [ ] 跑通了带引用溯源的 RAG 链，answer 和 sources 来自同一次检索
- [ ] 理解 Retriever 抽象让检索策略可替换（只改一处）
- [ ] 能把 LCEL 链的每个环节映射回手写版

下一课 [L05](../05_advanced_retrieval/) 是 LangChain 段收官：混合检索 + 多查询展开的工程化。
