# Lesson 08 练习

> 改 `code.py` 和 `eval/run_multimodal_eval.py` 里的代码，运行 `python code.py` 观察变化。本课 corpus 模式离线可跑，ragas 模式需 API key。

---

## 练习 1：加一道「图文混排」题，验证混排场景的评估

现在 golden_multimodal.json 的分类是 text/table/scan/chart。加一道图文混排题（P6 培训发展页，答案在文字部分）：

```json
{"id": "MIX01", "category": "mixed", "question": "连续两次绩效 A 可以怎样？",
 "ground_truth": "连续两次绩效 A 的员工可破格晋升。",
 "answer_tokens": ["破格", "晋升"], "source_page": 6}
```

在 `run_multimodal_eval.py` 的 `_corpus_for_config` 里确保 P6 的文字在语料，跑收益表看 mixed 类的通过率。

**思考**：图文混排题归哪类？——它的答案在**文字部分**（不在图里），所以走 text 路径就能答对。但如果问「晋升阶梯有几级」（答案在示意图里），就要走 chart/image 路径。**图文混排的评估关键是分清「答案在文字里还是在图里」**——这决定了它该被哪个机制点亮。

---

## 练习 2：构造「退化场景」，验证防退化检测

收益表的防退化行现在全 100%。人为构造一个退化场景，验证评估能检测到：

```python
# run_multimodal_eval.py 的 _corpus_for_config 里，全开配置故意漏掉一条纯文本
if chart_on:
    parts = [p for p in parts if "年假" not in p]  # 故意漏掉年假那条
```

跑收益表，看 text 题的通过率变化。

**思考**：text 题应该从 5/5 掉到 4/5——**防退化行检测到了退化**。这就是防退化行的价值：多模态升级如果意外删了/污染了纯文本 chunk，这行会立刻报警。**没有这行，你可能升级完才发现「图表能答了但年假答不了了」——拆东墙补西墙。**

---

## 练习 3（设计实验）：量「VLM 描述错误」对评估的影响

这是本课的**设计实验验证**题——亲手模拟 VLM 读错，验证 ragas 盲区。

在 `_corpus_for_config` 的图表描述里，故意把 Q3 的数值写错（模拟 VLM 读错）：

```python
# chart_on 的描述里，Q3 故意写成 1200（实际 2100，模拟 VLM 读错）
parts.append("柱状图 Q1:1800 Q2:2400 Q3:1200 Q4:2900")  # Q3 读错了
```

跑收益表，看 chart 题的通过率。

**思考**：
1. Q3 那题（answer_tokens=["2100"]）会 FAIL（语料里是 1200）——corpus 模式**能检测到**这个错误。
2. 但如果是真 ragas 模式，且答案用了错误的 1200：faithfulness 会判 PASS（答案忠于描述=1200）——**ragas 测不到**。
3. 对比两种模式的检测结果：corpus 模式靠 ground_truth 的 token 检测、ragas 靠「忠于材料」检测。**VLM 读错时，只有 corpus 模式（对照 ground_truth）能发现，ragas 盲区暴露**。这就是为什么 L04 的抽查兜底不可省。

---

## 练习 4（进阶）：实现 ragas 模式的完整跑通

现在 ragas 模式是骨架。实现完整版：

```python
# run_multimodal_eval.py run_ragas_mode 里：
# 1. 确保 poison PDF 已 ingest（开多模态开关）
# 2. 复用 run_eval.py 的 build_samples + ragas.evaluate
from eval.run_eval import build_samples
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_recall

golden = json.loads(GOLDEN_MM.read_text(encoding="utf-8"))
samples = build_samples(golden)  # 检索+生成
result = evaluate(samples, metrics=[faithfulness, answer_relevancy, context_recall])
```

**思考**：ragas 模式跑通后，对比 corpus 模式的数字——ragas 的 faithfulness 应该接近 1.0（答案忠于描述），但 context_recall 可能低（检索不一定命中图表描述）。**两个模式互补**：corpus 评「信息进库没」、ragas 评「端到端答案质量」。完整的评估要两层都跑。

---

## ✅ 完成本课后，你应该能回答

1. 收益表为什么用「逐机制开关矩阵」而不是简单的「升级前后」两行？
2. 防退化对照行为什么重要？它检测什么？
3. ragas 多模态盲区是什么？faithfulness 验证不了哪一层？
4. 盲区的兜底方案有哪些？（L04 抽查 + L06 区域引用）
5. 入库成本列显示哪个机制有显著成本？值得吗？
6. 多模态评估和 kb-qa 现有 eval 体系（run_eval/online_eval）什么关系？（离线扩展，不动线上）
7. （落地）run_multimodal_eval.py 的 corpus 模式和 ragas 模式各评什么？
