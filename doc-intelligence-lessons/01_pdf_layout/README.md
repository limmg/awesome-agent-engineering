# Lesson 01 — PDF 解剖与版面解析

> 本课目标：**手写一个版面感知的 PDF 解析器，产出带类型（text/table/image）和坐标（bbox）的元素流——这是五层架构的地基，后面每节课都建在它上面**。
>
> 学完你能回答面试官那句：**「扫描件你凭什么说它抽不到字？」**——因为扫描页根本没有文本层，看得见字 ≠ 有文本层，这是 PDF 解析的第一个分水岭。

---

## 1. PDF 的本质：三层结构

PDF 不是「带格式的文本」，是**一张张固定坐标的画布**——每个字、每张图、每条线都有精确的 (x, y) 坐标。理解 PDF 要先认清它的三层结构：

| 层 | 是什么 | 怎么读出来 | L00 毒文档里的例子 |
|---|---|---|---|
| **文本层** | 一串带坐标的文字片段（text span） | `page.get_text()` | P1 公司简介、P2 考勤制度 |
| **图片对象** | 嵌入的位图（JPEG/PNG） | `page.get_images()` | P3 扫描页（整页一张大图） |
| **矢量绘图** | 线段、矩形、曲线（drawing） | `page.get_drawings()` | P4 表格的框线（13 条线） |

> 🎯 **核心认知：看得见字 ≠ 有文本层。** 这句话是本课的起点。扫描件的字你是能「看见」的（它印在图上），但 PDF 里那页**没有文本层**——`get_text()` 返回空串。这是扫描件让 text-only 管线「全盲」的根本原因。

```
PDF 一页的解剖（PyMuPDF 视角）：

   page.get_text("dict") ──▶ blocks[]
                               │
                               ├── type=0 (text)  ──▶ lines[] ──▶ spans[]  每个带 bbox
                               └── type=1 (image) ──▶ 图片对象

   page.get_drawings()   ──▶ 矢量图元（线/矩形/曲线），表格框线在这
   page.get_images()     ──▶ 嵌入的图片清单
```

### 判定一页「是什么类型」的启发式

有了三层视图，就能给每页做分类（版面感知的第一步）：

| 条件 | 判定 | 依据 |
|---|---|---|
| 文本层字符数 ≈ 0 **且** 有图片 | **扫描页**（image） | 整页是图，没有可抽的文字 |
| 矢量线段 ≥ 6 条 | **表格页**（table） | 表格是网格，横竖线交叉 |
| 有文本 **且** 有图片 | **图文混排** | 文字走 text，图单独列 image |
| 仅文本 | **纯文本** | 走老路（切块入库） |

> 💡 **为什么用「线段数」判表格？** 因为表格的本质是「网格」——横线和竖线相交。纯文本页顶多有一条标题下划线（1-2 条），表格页会有十几条框线。阈值 6 是在毒文档上校准的（表格页 13 条、纯文本页 ≤2 条）。这不是通用版面模型（那要 MinerU），是**够用的启发式**——简单、零依赖、可解释。

---

## 2. 统一元素模型：Element

解析器的产物是一个统一的元素模型，后面所有课都消费它：

```python
@dataclass(frozen=True)
class Element:
    type: ElementType       # "text" | "table" | "image" —— 下游路由依据
    content: str            # text:文本 / table:串行文本(暂) / image:空(暂)
    page: int               # 页码 1-based —— L06 引用溯源的「P3」
    bbox: tuple[float, float, float, float]  # (x0,y0,x1,y1) —— L06 区域裁剪引用
    source: str             # 文件名
```

> 🎯 **为什么是 Element 而不是直接 Document？** 因为 LangChain 的 `Document` 只有 `page_content` + `metadata`，没有「类型」的概念。Element 是**类型感知的中间表示**——先认出「这是表格还是图片」，再决定怎么处理（表格走 L02 结构化、图片走 L03 OCR / L04 VLM）。类型路由是五层架构「解析层」的核心。

### 三个不变量（贯穿全程）

1. **类型确定路由**：text 走老路、table 走 L02、image 走 L03/L04。
2. **bbox 全程携带**：从 Element → Document metadata → Chroma → 生成层 → 引用。L06 的区域引用靠它，丢一次就回不到原图了。
3. **内容可分阶段填充**：L01 的 image 元素 content 为空，L03 的 OCR 会填上识别文本，L04 的 VLM 会填上描述。**Element 是个可逐步丰富、不可原地改的容器**（frozen=True，构造新对象）。

```
Element 的生命周期（跨课流转）：

   L01 parse_pdf      ──▶  type + bbox 确定，content 部分为空
       │
   L02 表格结构化     ──▶  table.content: 串行文本 → markdown/HTML
   L03 OCR            ──▶  image.content: 空 → 识别文本
   L04 VLM 描述       ──▶  image.content: 空/文本 → 结构化描述
       │
   L05 入向量库       ──▶  Element → Document(metadata 带 page/element_type/bbox)
       │
   L06 引用溯源       ──▶  bbox + page → 「文档 P3·表格」+ 区域裁剪图
```

---

## 3. 方案对比：三种 PDF 解析路线

| 方案 | 怎么做 | 保类型/坐标 | 安装成本 | 适合 |
|---|---|---|---|---|
| **纯文本抽取**（现状） | `page.get_text()` 一把梭 | 🚫 都丢 | 🟢 零 | 纯数字原生文档 |
| **版面感知解析**（本课） | 分层抽取 + 启发式分类，产出 Element | ✅ type + bbox | 🟢 PyMuPDF 一包 | 企业级混合文档（主路线） |
| **版面模型管线** | MinerU/unstructured，深度学习判版面 | ✅ 更准 | 🔴 torch + 模型权重，Windows 坑多 | 文档量极大、版面极复杂 |

```
三种路线的「看得见 vs 读得到」能力：

   纯文本抽取：   只读【文本层】            → 扫描/图表全瞎
   版面感知(本课)：读【三层】+ 分类路由     → 认得出类型，内容待后续课翻译
   版面模型：     深度学习判版面区域        → 更准但重，本课作参照不依赖
```

> 🎯 **本课选「版面感知解析」的理由**：它用 PyMuPDF 一个包就能认清三类杀手页的类型（零额外依赖、CPU 可跑），把「这是什么元素」的问题解决了。「内容怎么翻译」是后面每课的事——表格的结构化（L02）、扫描的 OCR（L03）、图表的 VLM（L04）。**分层的好处是每层只做自己擅长的事，不搞一刀切。**

### 为什么不直接上 MinerU？

MinerU 是优秀的版面模型管线，但本课**只作参照**：

| 维度 | 版面感知解析（本课） | MinerU |
|---|---|---|
| 原理 | 启发式分类（线段数/图片/文本量） | 深度学习版面模型 |
| 精度 | 够用（常见版面准确） | 更高（复杂版面、公式、跨栏） |
| 安装 | `pip install PyMuPDF` | torch + 模型权重，Windows 常踩坑 |
| 透明度 | 全可见（30 行分类逻辑） | 黑盒（模型推理） |
| 教学价值 | 讲透「为什么这样分类」 | 讲不清模型内部 |

> 💡 理解了版面感知解析的分类逻辑，迁移到 MinerU 只是换底层引擎，Element 模型和五层架构不变。**先懂为什么分类，再选用什么分类器。** 这是和 RAG 课「先手写 ReAct 再用框架」一脉相承的思路。

---

## 4. 落地：接入 kb-qa 的 ingest

本课第一次改 kb-qa 代码。核心原则：**默认全关，79 个现有测试始终绿。**

### 4.1 新增 `src/kb_qa/doc_parser.py`

`Element` 模型 + `parse_pdf(pdf_path) -> list[Element]` + `summarize()` 报告。分类逻辑（扫描/表格/图文/纯文本）的启发式阈值集中在模块顶部，可调。

### 4.2 config 加开关

```python
# src/kb_qa/config.py
enable_multimodal_ingest: bool = False   # 默认关：行为同升级前
ocr_engine: str = "off"                  # L03 用
table_format: str = "markdown"           # L02 用
enable_image_caption: bool = False       # L04 用
vision_model: str = "glm-4v-plus"        # L04 用
enable_voice: bool = False               # L07 用
```

> 🎯 **所有多模态开关默认关闭。** 这是硬约束：开箱即用 = 行为同升级前，79 个现有测试零修改全绿。想用多模态，显式 `.env` 配 `ENABLE_MULTIMODAL_INGEST=true`。

### 4.3 ingest 按 suffix + 开关路由

```python
# ingest_directory 里：
if path.suffix == ".pdf" and settings.enable_multimodal_ingest:
    chunks = _load_pdf_as_documents(path)   # 走版面感知解析
else:
    chunks = load_and_split(path)           # 走老路（md/txt）
```

`_load_pdf_as_documents` 把 Element 流转成 Document，metadata 带 `page`/`element_type`/`bbox`（L06 引用溯源用），同时保留 `source`/`src_hash`/`chunk_idx`（增量缓存用）。**空内容的 image 元素此时跳过**（OCR/描述未启用时入空 chunk 会污染向量库），L03/L04 会把它们填上再入。

---

## 5. 本课代码会做什么

### `code.py`（教学，可独立跑）
- ① PDF 三层结构体检：逐页打印文本层字符数 / 图片数 / 矢量线段数 + 判定
- ② 跑 `parse_pdf`，逐页打印元素类型统计（P3: 1 image、P4: 1 table、P5: 2 text + 1 image）
- ③ before/after 对比：朴素 `get_text()` vs 版面感知，看三类杀手页从「看不见」到「认得出」

### 落地到 kb-qa
- 新增 `src/kb_qa/doc_parser.py`（Element + parse_pdf + summarize）
- `config.py` 加 6 个多模态开关（全默认关）
- `ingest.py` 加 `_load_pdf_as_documents` + 按 suffix 路由（开关 off 时走老路）
- 新增 `tests/test_doc_parser.py`（10 个测试，含开关 on/off 回归）

---

## 6. 跑起来

### 教学代码（独立可跑）
```bash
cd doc-intelligence-lessons/01_pdf_layout
python code.py
```
预期：P3 扫描页判为 image、P4 表格页判为 table、P5 图表页图文分离。

### 落地验证（kb-qa）
```bash
cd portfolio-projects/knowledge-base-qa
# 1) 新增的解析器测试（全本地，用毒文档）
python -m pytest tests/test_doc_parser.py -q          # 10 passed
# 2) 全量回归（开关默认 off，79 个老测试不受影响）
python -m pytest -q                                     # 89 passed (79 + 10)
# 3) 手动验证开关 on：把毒文档丢进 docs/，开多模态
cp ../../data/multimodal_docs/company_briefing.pdf data/docs/
ENABLE_MULTIMODAL_INGEST=true python -c "
from kb_qa.config import settings
import kb_qa.ingest as ing
# 注意：这会调真 embedding，需要 ZHIPUAI_API_KEY
print(ing.ingest_directory('data/docs'))
"
```

### 验收检查
- [ ] `parse_pdf(毒文档)` 产出 text/table/image 三类元素，各带 page + bbox
- [ ] P3 扫描页 → image（不是空 text）；P4 表格页 → table；P5 图文分离
- [ ] 纯文本文档（.md）在新旧路径下抽取结果等价（开关 off 时完全不变）
- [ ] `pytest tests/test_doc_parser.py` 全绿；`pytest -q` 共 89 passed
- [ ] 开关 on 时 PDF 入库的 chunk metadata 带 `page`/`element_type`/`bbox`

---

## 🎯 面试话术

> 「我的入库管线是版面感知的：PDF 不是一把 get_text 梭哈，而是先认清三层结构——文本层、图片对象、矢量绘图。每个元素带类型（text/table/image）和坐标 bbox，分类路由到不同处理链路。扫描页字符数=0 就判 image、矢量线段多就判 table、图文混排就把图单列出来。坐标全程携带，是后面区域级引用溯源的地基。选 PyMuPDF 手写分类而非直接上 MinerU，是因为这层只需认出类型，深度学习版面模型在这里是杀鸡用牛刀、还难装。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/kb_qa/doc_parser.py` | **新增**：`Element` 模型 + `parse_pdf` + `summarize` | `python -c "from kb_qa.doc_parser import parse_pdf; print(len(parse_pdf('毒文档')))"` |
| `src/kb_qa/config.py` | 加 6 个多模态开关（`enable_multimodal_ingest`/`ocr_engine`/`table_format`/`enable_image_caption`/`vision_model`/`enable_voice`），全默认关 | `python -c "from kb_qa.config import settings; print(settings.enable_multimodal_ingest)"` → False |
| `src/kb_qa/ingest.py` | 加 `_load_pdf_as_documents`；`ingest_directory` 开关 on 时纳入 PDF、按 suffix 路由 | 开关 off 跑 `pytest -q` → 79 老测试全绿 |
| `tests/test_doc_parser.py` | **新增**：10 个测试（解析分类 + 开关 on/off 回归 + 幂等） | `pytest tests/test_doc_parser.py -q` → 10 passed |

> 📌 **两条主线位置**：本课在**成本-精度主线**上立了「版面感知分类几乎免费（PyMuPDF 本地），VLM 留给真正需要看图的 L04」；在**溯源主线**上立了地基——Element 的 `page` + `bbox` 从这里开始全程携带，L06 的「页码+区域」引用就靠它。

下一课 [Lesson 02 — 表格：从串行文本到结构化上下文](../02_table/) 解决 table 元素的 content——用 pdfplumber 把串行文本升级成 markdown/HTML，并用对照实验裁决哪种表示最划算。
