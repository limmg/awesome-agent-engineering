# 成本/质量选型报告（LLMOps L12）

> 同一 golden set 下生成模型对比。
>
> ⚠️ **本机未实测真实数据**（执行环境不调大量真实智谱 API）。
> 本文件是报告模板 + 方法论；跑一次 `python eval/run_cost_eval.py --limit 5` 后会自动覆写「质量对比」「成本对比」表。

## 怎么跑

```bash
cd portfolio-projects/knowledge-base-qa
python eval/run_cost_eval.py --limit 5      # 冒烟（5 题 × 2 模型）
python eval/run_cost_eval.py                # 全量（20 题 × 2 模型）
```

## 质量对比

> 跑一次后自动填入。

| 模型 | faithfulness | answer_relevancy | context_precision | context_recall |
|------|-------------|------------------|-------------------|----------------|
| _待填入_ | | | | |

## 成本对比

| 模型 | 总成本 | 单题成本 |
|------|--------|----------|
| _待填入_ | | |

## 预期结论（基于架构分析的先验判断）

kb-qa 现有配置 `answer_model=glm-4` / `rewrite_model=glm-4-flash`，本评估用于**用数据验证这个选择**：

- **生成环节 → glm-4**：faithfulness（防幻觉）是知识库问答的生命线，flash 在生成上 faithfulness 预期明显低于 glm-4（更爱编造），核心质量不能省。
- **改写/judge → glm-4-flash**：改写只需语法正确、judge 只需判断好坏，质量要求低；且 flash 免费、量大。这两个环节用 flash 是「质量够用 + 零成本」的最优。
- **context 指标是对照组**：context_precision/recall 取决于检索（两模型用同一个 KBRetriever），应基本相同。若差异大说明实验有问题（非模型因素）。

## 成本量级估算

按价目表（glm-4: 50元/百万token，flash: 免费），假设每题 in≈800 out≈200 token：

| 配置 | 单题成本 | 1000 题成本 |
|------|---------|------------|
| 全程 glm-4 | ~¥0.05 | ~¥50 |
| 全程 flash | ¥0（免费） | ¥0 |
| **混合（生成 glm-4 + 辅助 flash）** | ~¥0.05（生成贵，辅助免费） | ~¥50 |

> 混合配置的成本主要由生成环节决定（辅助环节 flash 免费），但保证了核心质量。
> 这就是「把钱花在刀刃上」——省辅助环节的钱，不省核心环节的质量。

## 关键认知

**模型选型不是「全用最贵」或「全用最便宜」，而是按环节分工**：
- 质量敏感环节（生成）→ 强模型（glm-4）
- 量大不敏感环节（改写/judge）→ 快模型（flash）
- 用 ragas 数据验证每个选择，而非拍脑袋。

这是质量-成本-延迟三角的工程权衡：用评估管线把「直觉」变成「数据支撑的决策」。
