# 检索质量评估报告（ragas 消融对比）

- **评估集**：golden_set.json，20 题（14 单一事实 / 4 同文档综合 / 2 口语化换说法），覆盖 8 个企业文档
- **评估器**：ragas 0.4.3，judge = glm-4，embedding = embedding-3（与线上同款，不引 OpenAI）
- **对比对象**：三种检索模式，其余环节（分块/生成 prompt/模型）完全一致
- **运行**：`python eval/run_eval.py --modes vector hybrid rerank`（2026-07-10，逐题分数见 results.json）

## 结果

| 指标 | vector（纯向量） | hybrid（BM25+向量） | rerank（混合+重排） |
|---|---|---|---|
| context_recall（检索：该找的找到了吗） | 0.9250 | 0.9000 | **0.9750** |
| context_precision（检索：排序质量） | 0.8333 | **0.8796**¹ | 0.8583 |
| faithfulness（生成：忠于材料吗） | 0.8028 | 0.7488 | **0.8483** |
| answer_relevancy（生成：切题吗） | 0.6058 | 0.6431 | **0.6524** |

¹ hybrid 的 context_precision 有 2 题 judge 调用超时，均值基于其余 18 题。

## 逐指标诊断

**context_recall：rerank 0.975，三者最高（+5pp vs vector）。**
完整管线先用混合检索扩大召回池（k=8），再由 cross-encoder 从中选出真正相关的 4 条——
「宽进严出」策略同时压住了纯向量的语义漂移和纯截断的排序噪声。这是 reranker 价值的最直接证据。

**context_precision：hybrid 最高（0.88），rerank 略低（0.86）。**
智谱 rerank 模型存在分数饱和现象（大量候选精确返回 1.0，见 src/kb_qa/rerank.py 注释），
区分度不足时我们让同分候选退回混合检索的排序，因此 rerank 的排序上限受限于此。
若换用区分度更好的 rerank 模型（如 bge-reranker），此项还有提升空间——这是当前管线最明确的优化方向。

**faithfulness：hybrid 单独使用反而最低（0.75），rerank 拉回到 0.85。**
混合召回扩大了池子但 BM25 会引入「词面命中、语义无关」的噪声材料，LLM 在噪声材料上更容易过度发挥；
重排把噪声压到 top-4 之外后，faithfulness 恢复并超过纯向量基线。
结论：**混合检索必须配 reranker 使用**，只开混合不开重排是负优化。

**answer_relevancy：三者都在 0.6 档，相对偏低。**
该指标用「从答案反推问题再算 embedding 相似度」实现，中文短答案 + 答案里的【材料N】引用标记
都会拉低反推质量，属于指标特性而非管线缺陷（逐题看无明显跑偏样本）。
若要优化：评估时剥离引用标记后再算，或改用 LLM 直评的 relevancy 变体。

## 结论

1. **生产默认配置 = rerank 模式**（ENABLE_RERANK=true）：召回、忠实度、切题度三项最优。
2. reranker 的量化价值：context_recall +5pp、faithfulness +4.5pp（vs 纯向量基线）。
3. 已知瓶颈与后续方向：智谱 rerank 分数饱和 → 换 bge-reranker 类模型；answer_relevancy 指标本身对中文引用式答案偏严。
