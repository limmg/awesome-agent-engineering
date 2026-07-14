# Lesson 05 — 多模态检索：图片怎么被搜到

> 本课目标：**打通「文字 query 检索到图片元素」的链路——用描述索引让图表可被搜到，命中后按 element_type 路由（image→现场看图、table→结构化、text→文本直答）**。
>
> 学完你能回答面试官那句：**「图片怎么被文字搜到？CLIP 双塔不就行了？」**——描述索引路线与现有 Chroma 无缝、VLM 费用入库时一次性、精度取决于描述质量；CLIP 省 VLM 但多一套模型栈，我的量级下描述索引更划算。

---

## 1. 问题：图片在向量库里是「隐形」的

L04 让图表有了结构化描述，但描述还只是在 image 元素的 content 里。**图片本身不能直接被 embedding 检索**——embedding-3 是文本模型，它 embedding 不了图片像素：

```
文字 query「Q3 营收趋势」检索时的困境：

   向量库里有什么？
   ├── text 元素：「公司简介」「考勤制度」...     ← 能被检索
   ├── table 元素：薪酬表 markdown                 ← 能被检索
   └── image 元素：图表描述（L04 填的）            ← 能被检索（描述是文本！）
   
   → 如果 image 元素的描述入库了，文字 query 就能命中它
   → 如果没入库（enable_image_caption=off），图表在库里是隐形的
```

> 🎯 **核心认知**：图片本身不可检索，但**图片的描述是文本，文本可检索**。描述索引的本质是「用 VLM 把图翻译成文本，让文本检索器能搜到它」。这是连接多模态和现有 RAG 的桥梁。

---

## 2. 方案对比：多模态检索的三个流派（本课灵魂）

| 流派 | 怎么做 | VLM 费用 | 本地模型 | 检索精度 | 与现有架构 |
|---|---|---|---|---|---|
| **描述索引**（主路线） | 图→VLM描述→embedding-3 入 Chroma | 有（入库一次性） | 无 | 🟢 高 | ✅ 无缝（描述就是文本） |
| **CLIP 双塔**（可选） | 图文同空间，免描述 | 无 | 有（torch+chinese-clip） | 🟡 中 | 🟠 多一套模型栈 |
| **整页截图直检** | 逐页 VLM 扫描 | 有（每页都扫） | 无 | 🟡 低 | 🚫 只适合评估 |

### 为什么选描述索引？

```
描述索引的工作流（与现有 Chroma 零摩擦）：

   入库时：
   图片 → glm-4v-plus → 结构化描述 → embedding-3 → 同一个 Chroma 库
   （metadata: element_type=image, page, bbox）
   
   检索时：
   文字 query → embedding-3 → 搜同一个库 → 命中描述（image 元素）
   → 看 metadata: element_type=image → 路由到现场看图
```

> 🎯 **描述索引胜出的三个理由**：① **零架构改动**——描述就是文本，进同一个 Chroma，现有检索/rerank 全复用；② **VLM 费用入库时一次性**——重复问同一张图不重复花（L04 的缓存）；③ **精度取决于描述质量**——L04 的结构化 prompt 已保证描述含数值/标签/趋势。

### CLIP 双塔为什么不选（作可选实验）

CLIP 把图片和文本映射到**同一个向量空间**——图片直接 embedding，不需要 VLM 先描述。理论上更优雅（免 VLM），但：

| 维度 | 描述索引 | CLIP 双塔 |
|---|---|---|
| 依赖 | 无（用现有 embedding-3） | torch + chinese-clip 模型 |
| 安装 | 已就绪 | 重（torch 几 GB，Windows 坑多） |
| 中文效果 | ✅ embedding-3 原生中文 | 🟡 依赖 chinese-clip 质量 |
| 费用 | VLM 入库一次性 | 免费（但模型栈重） |
| 精度 | ✅ 描述含语义细节 | 🟡 图文匹配较粗 |

> 💡 **本课量级下描述索引更划算**：企业知识库的图片量不大（几百到几千张），VLM 描述一次性的成本可接受，换来的是零架构改动 + 高精度。CLIP 的优势在「海量图片 + 无 VLM 预算」的场景——那是另一个量级的问题。**工程选型看场景，不是看技术先进性。**

---

## 3. 统一索引 vs 分库

描述索引选**统一库**（同一个 Chroma，metadata 区分 element_type），而非图片单独建库：

| 方案 | 优点 | 缺点 |
|---|---|---|
| **统一库**（本课） | 一次检索覆盖所有类型；rerank 统一排序 | 要按 element_type 路由 |
| **分库**（图/文/表各一个） | 类型隔离干净 | 多次检索、结果难融合 |

```
统一库的检索结果（按 element_type 路由）：

   query「Q3 营收」→ 检索统一库 → top results:
   ├── [image, P5] 图表描述（含 Q3:2100）  → 路由：现场看图
   ├── [text, P5]  「上图为本年度各季度营收」→ 文本直答（信息不足）
   └── [table, P4] 薪酬表                   → 不相关（rerank 会降权）
```

> 🎯 **统一库 + metadata 路由**是成本最低的方案：一次检索拿全所有类型，按 element_type 决定怎么消费。分库要检索多次（图库+文库+表库），结果融合复杂。

---

## 4. 检索结果路由：命中后怎么消费

`service.py` 的检索结果按 `element_type` 路由到不同的生成路径：

```python
# service.py stream_ask 里（L05 落地）：
sources_payload = [{
    "idx": i,
    "source": ...,
    "element_type": d.metadata.get("element_type", "text"),  # L05 新增
    "page": d.metadata.get("page"),                          # L05/L06 新增
    ...
} for i, d in enumerate(docs, 1)]

# 路由逻辑（概念）：
# top1 的 element_type 决定生成方式：
#   image → answer_with_image（L04 现场看图，最忠实）
#   table → stream_answer（markdown/HTML 进 prompt，L02）
#   text  → stream_answer（老路，文本直答）
```

> 💡 **路由的时机**：检索完拿到 docs 后、生成前。不是每问都看图，是**命中图表时才看**。这控制了 VLM 成本——大部分问题是文本题，走免费的 stream_answer；只有图表题才花钱现场看图。

---

## 5. 实测：描述索引让图表可被搜到

`code.py` 用 token 重叠近似检索（无需真 embedding，离线可跑），对比 text-only vs +描述索引：

```
query「Q3 的营收是多少万元」
  text-only（无描述索引）    → top1: P5 [text] score=2  🟡 命中标题(无数值)
  +描述索引（L04 描述入库）   → top1: P5 [image] score=5 ✅ 命中描述(含2100)

query「哪个季度营收最高」
  text-only                  → score=4 🟡 标题
  +描述索引                   → score=6 ✅ 描述（含"Q4最高"）
```

> 🎯 **描述索引把检索 score 从 2 提到 5（2.5x）**，而且命中的是含数值的描述，不是空标题。真 embedding-3 的语义匹配效果更好（token 重叠是下限）。

---

## 6. 本课代码会做什么

### `code.py`（近似检索，离线可跑）
- ① 图表题检索对照：text-only vs +描述索引（token 重叠近似，演示量级差异）
- ② 路由演示：image→现场看图、table→结构化、text→文本直答
- ③ CLIP 双塔 vs 描述索引 vs 整页截图 方案对比

### 落地到 kb-qa
- `service.py` sources_payload 带 `element_type`/`page`（L06 引用也要用）
- ingest 已支持图片描述入库（L04 的 `_load_pdf_as_documents`，element_type=image 的 chunk 入 Chroma）
- `tests/test_multimodal_retrieval.py`：4 个测试（sources 带 type + 描述可检索）

---

## 7. 跑起来

### 教学代码（近似检索，离线）
```bash
cd doc-intelligence-lessons/05_multimodal_retrieval
python code.py
```
预期：描述索引 score 2.5x 于 text-only，路由表展示三种 element_type。

### 落地验证（kb-qa）
```bash
cd portfolio-projects/knowledge-base-qa
python -m pytest tests/test_multimodal_retrieval.py -q        # 4 passed
python -m pytest -q                                            # 124 passed
```

### 验收检查
- [ ] 描述索引让图表题检索 score 提升（token 重叠近似）
- [ ] 路由表：image→现场看图、table→结构化、text→文本直答
- [ ] `service.py` 的 sources 事件带 element_type/page
- [ ] 硬任务图表题端到端：检索命中图表→（L04）看图→答对
- [ ] 纯文本检索行为不变（回归）

---

## 🎯 面试话术

> 「多模态检索我选描述索引路线：图片的结构化描述进同一个 Chroma 库，metadata 带 element_type，一次检索覆盖所有类型，命中后按类型路由——image 现场看图、table 结构化作答、text 文本直答。描述索引与现有架构零摩擦（描述就是文本），VLM 费用入库时一次性（L04 缓存去重）。CLIP 双塔我对比过——省 VLM 费用但多一套 torch+chinese-clip 模型栈，我的量级下描述索引更划算。整页截图直检太贵，只适合评估。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/kb_qa/service.py` | sources_payload 加 `element_type`/`page`（L05/L06 共用） | stream_ask 的 sources 事件含 element_type 字段 |
| `src/kb_qa/ingest.py` | 图片描述入库已支持（L04 的 `_load_pdf_as_documents`，element_type=image） | 开 `enable_image_caption` 后图表描述进 Chroma |
| `tests/test_multimodal_retrieval.py` | **新增**：4 个测试（sources 带 type、PDF chunk 带 type、描述可检索） | `pytest tests/test_multimodal_retrieval.py -q` → 4 passed |

> 📌 **两条主线位置**：本课在**成本-精度主线**上是描述索引 vs CLIP 的取舍——描述索引 VLM 入库一次性、CLIP 免 VLM 但模型栈重；在**溯源主线**上，sources 带 `element_type`/`page`/`bbox`，检索结果可追溯到具体元素和位置（L06 引用格式的数据来源）。

下一课 [Lesson 06 — 引用溯源升级：回到原文档](../06_citation/) 把引用从「chunk 文本」升级到「文档+页码+区域」，完成可信度三部曲的第三步。
