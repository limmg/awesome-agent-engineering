# Lesson 08 — 多模态评估：收益表

> 本课目标：**扩充 golden set，量化全部多模态机制的收益，出最终收益表对照 L00 基线，并守住「不伤老能力」的底线**。
>
> 学完你能回答面试官那句：**「升级收益怎么证明？ragas 能评多模态吗？」**——逐机制收益表 + 纯文本回归防退化行 + 入库成本列；ragas 能评「答案忠于描述」，评不了「描述忠于原图」——盲区和兜底我都讲得清。

---

## 1. 评估设计：逐机制开关矩阵

不是只跑「升级前 vs 升级后」两行，而是**逐机制开关**，看每个机制点亮了哪类题：

| 配置 | text | table | scan | chart | 成本 |
|---|---|---|---|---|---|
| text-only（L00 基线） | 5/5 | 0/3 | 0/3 | 0/4 | ~0.001元 |
| +表格（L02） | 5/5 | **3/3** | 0/3 | 0/4 | ~0.001元 |
| +表格+OCR（L02+L03） | 5/5 | 3/3 | **3/3** | 0/4 | ~0.001元 |
| 全开（+图表 L04） | 5/5 | 3/3 | 3/3 | **4/4** | ~0.076元 |

> 🎯 **核心认知**：每个机制精准点亮一类题——表格机制点亮 table、OCR 点亮 scan、图表描述点亮 chart。这不是巧合，是**分类路由架构**的必然结果：每个机制只处理自己负责的元素类型，互不干扰。

### 防退化对照（别人常忘的一行）

```
所有配置下 text 题 = 5/5 = 100%
→ 多模态升级没伤老能力 ✅
```

> 💡 **为什么这行重要**：很多人做多模态升级后，纯文本检索反而变差了（多模态 chunk 污染了向量库、或 metadata 路由出错）。**防退化行证明升级是「只加不减」**——老能力全保留，新能力叠加上去。这是收益表里最重要的一行。

---

## 2. ragas 在多模态场景的适配难题（本课灵魂）

ragas 的 faithfulness 指标验证「答案忠于材料」，但多模态下「材料」是 VLM 描述文本而非原图——**judge 只能验证「答案忠于描述」，验证不了「描述忠于原图」**：

```
ragas 能评的（faithfulness 链路）：
   原图 → VLM 描述 → [材料] → 答案
                          ✅ ragas 验证这段
   
ragas 评不了的（盲区）：
   原图 → VLM 描述
   🚫 这段 ragas 看不见
   
   如果 VLM 把 2100 读成 1200：
   - 描述里是 1200
   - 答案「1200」忠于描述 → faithfulness = 1.0 ✅（ragas 说对）
   - 但实际答错了（原图是 2100）→ 真实错误 🚫
```

> 🎯 **盲区的兜底**：① L04 的「描述质量抽查」（按概率重新描述对比）；② L06 的区域引用（用户可裁剪原图核对）。**ragas 测不到的层，用抽查 + 用户核对兜底**。诚实标注这个盲区比假装 ragas 万能更有可信度。

---

## 3. 入库成本列（成本-精度主线闭环）

收益表附入库成本估算，让每个机制的「性价比」可见：

| 机制 | 成本 | 收益 | 性价比 |
|---|---|---|---|
| 表格结构化（L02） | 0 元（本地 pdfplumber） | table 0→100% | 🟢 纯赚 |
| OCR（L03） | 0 元（本地 RapidOCR） | scan 0→100% | 🟢 纯赚 |
| 图表描述（L04） | ~0.075 元/图（VLM） | chart 0→100% | 🟡 花钱但值得 |

> 💡 **图表描述是唯一有显著成本的机制**，但它把 chart 题从 0% 拉到 100%——这笔钱值得。其他机制本地免费，纯赚。这就是分类路由的价值：**成本只在真正需要 VLM 的地方产生**。

---

## 4. 与 kb-qa 现有 eval 体系的关系

| 评估 | 用途 | 数据 | 多模态改动 |
|---|---|---|---|
| `run_eval.py`（现有） | 检索质量消融（vector/hybrid/rerank） | golden_set.json（20 题纯文本） | 不动 |
| `run_attack.py`（现有） | 注入攻防 | attack_set.json | 不动 |
| `run_cost_eval.py`（现有） | 成本核算 | 线上 trace | 不动 |
| **`run_multimodal_eval.py`**（本课新增） | 多模态机制收益 | golden_multimodal.json（15 题） | 新增离线扩展 |

> 🎯 **多模态评估是离线 golden 扩展，不动线上闭环**。线上评估（online_eval）仍走原 golden_set 的采样+judge；多模态收益表是离线跑的，证明升级效果用。

---

## 5. 本课代码会做什么

### `code.py`（离线，零 API）
- ① 收益表：逐机制开关矩阵 × 4 类题型
- ② 逐机制收益：每个机制点亮哪类题
- ③ 防退化对照：纯文本题全配置 100%
- ④ ragas 盲区：诚实标注 + 兜底方案
- ⑤ 入库成本列：成本-精度闭环

### 落地到 kb-qa
- 新增 `eval/golden_multimodal.json`：15 题（text5 + table3 + scan3 + chart4）
- 新增 `eval/run_multimodal_eval.py`：corpus 模式（离线）+ ragas 模式（需 key）
- 输出 `eval/multimodal_report.json` 收益表档案

---

## 6. 跑起来

### 教学代码（离线）
```bash
cd doc-intelligence-lessons/08_evaluation
python code.py
```
预期：收益表显示 table/scan/chart 逐机制 0→100%，text 全配置 100%。

### 落地验证（kb-qa）
```bash
cd portfolio-projects/knowledge-base-qa
# corpus 模式（离线）
python eval/run_multimodal_eval.py                    # 打印收益表
# ragas 模式（需 API key + 预入库毒文档）
python eval/run_multimodal_eval.py --mode ragas
```

### 验收检查
- [ ] 收益表至少含「text-only vs 全开」两行
- [ ] 纯文本题分数不低于升级前（防退化 100%）
- [ ] 逐机制：table/scan/chart 各自从 0% 爬到 100%
- [ ] ragas 多模态盲区诚实标注
- [ ] 无 API 时 corpus 路径能演示全流程

---

## 🎯 面试话术

> 「多模态升级我有收益表：每类杀手题逐机制 before/after——表格 0→100%（L02）、扫描 0→100%（L03）、图表 0→100%（L04），每个机制的收益独立可见。还有一行别人常忘的——纯文本回归题，全配置 100%，证明升级没伤老能力。入库成本列显示表格和 OCR 本地免费、图表描述 VLM 每图 0.075 元但把 chart 题从 0 拉到 100，值得。ragas 在多模态下有盲区：faithfulness 验证『答案忠于描述』，验证不了『描述忠于原图』——这层我靠 L04 描述抽查 + L06 区域引用兜底，盲区和兜底都讲得清。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `eval/golden_multimodal.json` | **新增**：15 题多模态 golden（text5+table3+scan3+chart4） | `python -c "import json;print(len(json.load(open('eval/golden_multimodal.json'))))"` → 15 |
| `eval/run_multimodal_eval.py` | **新增**：corpus 模式（离线）+ ragas 模式（需 key）+ 收益表输出 | `python eval/run_multimodal_eval.py` 打印收益表 |

> 📌 **两条主线位置**：本课是**成本-精度主线**的收尾——收益表 + 入库成本列量化了每个机制的性价比；在**溯源主线**上，ragas 盲区（描述忠不忠于原图）的兜底正是 L06 的区域引用（用户可核对原图），两条主线在此闭环。

下一课 [Lesson 09 — 毕业整合：kb-qa v3 + 全仓重编号](../09_capstone/) 全机制协同跑通硬任务，完成 v3 定稿与全仓课程重编号。
