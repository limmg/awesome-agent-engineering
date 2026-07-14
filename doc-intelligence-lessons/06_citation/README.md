# Lesson 06 — 引用溯源升级：回到原文档

> 本课目标：**把引用从「chunk 文本」升级到「文档+页码+区域(bbox)」——多模态材料都是转换的产物，转换就会错，用户必须能一键回到原始位置核对。这是可信度三部曲的第三步**。
>
> 学完你能回答面试官那句：**「表格里的数字、图表的读数，用户怎么知道你答对了？」**——引用带页码和区域，可裁剪原图核对；数字给不出出处就拒答。

---

## 1. 为什么多模态下旧引用不够

旧引用格式是 `【材料1】（出处：hb.md · 手册 > 假期）`——对纯文本文档够用，但多模态下有三个致命问题：

| 问题 | 旧引用的后果 | 新引用怎么解 |
|---|---|---|
| **表格是转换产物** | 用户看到「22000」不知是哪一行哪一列 | 「briefing.pdf · P4·表格」+ 裁剪图 |
| **图表是 VLM 读的** | VLM 可能读错，用户没法核对 | 区域裁剪回到原图柱状图 |
| **OCR 是识别的** | OCR 可能识别错，用户看不到原图 | 扫描页 bbox 回到原扫描影像 |

> 🎯 **核心认知**：多模态材料的每个数字/文字都是**转换的产物**（表格抽取、VLM 读图、OCR 识别），转换就可能错。旧引用只说「来自某文档」，用户无法核对具体位置。新引用必须精确到**页码+区域**，让用户能裁剪原图一眼验证。

```
可信度三部曲（作品集的核心卖点）：

   ① frontier 让数字【可复算】
      代码解释器：用户能复算 Agent 给出的数字（透明计算过程）

   ② gui 让来源【可回访】
      浏览器证据链：用户能点开 Agent 引用的网页验证（可回访链接）

   ③ 本课让引用【可回溯】          ← 你在这里
      页码+区域：用户能回到原文档的具体位置核对（可回溯引用）
```

---

## 2. 引用三级：text → page → region

| 级别 | 格式 | 代价 | 可信度 | 适合 |
|---|---|---|---|---|
| **text**（旧） | `hb.md · 手册 > 假期` | 🟢 零 | 🟡 文档级 | 纯文本文档（md/txt） |
| **page**（默认） | `briefing.pdf · P4·表格` | 🟢 零 | 🟢 页+类型级 | 多模态默认 |
| **region**（最可信） | `+ 裁剪图 clips/P4_...png` | 🟡 生成裁剪图 | 🟢🟢 区域级 | 关键数字、争议内容 |

```
三级引用的精度递进：

   text:   「来自 briefing.pdf」                ← 哪一页？不知道
   page:   「briefing.pdf · P4·表格」           ← 第 4 页的表格
   region: 「briefing.pdf · P4·表格 + 裁剪图」  ← 就是这块区域，看图
```

> 💡 **默认用 page 级，争议时升级 region**。page 级零成本（metadata 已有），region 级要调 PyMuPDF 裁剪（`get_pixmap(clip=bbox)`）。关键数字（如薪酬、营收）值得 region 级——用户核对成本最低。

---

## 3. 方案对比：引用的三种实现路径

| 方案 | 怎么做 | 代价 | 可信度 |
|---|---|---|---|
| **纯文字引用**（旧） | `source · section` | 🟢 轻 | 🟡 文档级 |
| **页码引用**（本课默认） | `source · P{page}·{type}` | 🟢 轻 | 🟢 页级 |
| **区域截图引用**（可选） | + PyMuPDF 裁剪图 | 🟡 中（生成文件） | 🟢🟢 区域级 |

> 🎯 **本课默认 page 级，region 做成可选**。理由：page 级对大多数场景够用（用户翻到那页就能核对），region 级的裁剪图在「关键数字、用户质疑、法律合规」场景才值得生成。配置化让用户按需升级，不强加成本。

### 区域裁剪的实现

```python
def clip_region(pdf_path, page, bbox, out_dir, dpi=150):
    """PyMuPDF 裁剪 PDF 指定页的指定区域为 PNG。"""
    doc = fitz.open(pdf_path)
    page_obj = doc[page - 1]  # 1-based → 0-based
    clip = fitz.Rect(*bbox)   # (x0, y0, x1, y1)
    pix = page_obj.get_pixmap(dpi=dpi, clip=clip)
    doc.close()
    out_file = out_dir / f"{stem}_P{page}_{bbox_str}.png"
    pix.save(out_file)
    return out_file
```

> 💡 bbox 从哪来？**L01 的 Element.bbox 全程携带**——解析时记录、入库时进 metadata、检索时返回、L06 裁剪时用。这条链路断一节，区域引用就回不到原图。这就是为什么 L01 强调「bbox 全程携带」。

---

## 4. 防幻觉强化：数字必须给出处

多模态升级后，防幻觉纪律（延续 rag-L05）更关键：

```
数字类问题的回答纪律：

   有出处（检索命中 + 答案在材料里）
     → 「P5 基本工资 22000（出处：briefing.pdf · P4·表格）」✅

   无出处（检索没命中 / 答案不在材料里）
     → 「材料中未找到相关信息」🚫（不编造）
```

> 🎯 **为什么多模态下防幻觉更重要**：因为多模态材料的数字来自转换（OCR/VLM/表格抽取），转换错了就是系统性错误。如果还允许「无出处作答」，错误会被放大。**数字给不出出处就拒答**——这是可信度的底线。

---

## 5. 落地：改了哪些 kb-qa 文件

### `generate.py` build_context（引用格式升级）

```python
# 旧：loc = f"{src} · {section}" if section else src
# 新：page/element_type 缺失时不变（向后兼容）；有时加页码引用
if section:
    loc = f"{src} · {section}"
elif page and element_type:
    type_cn = {"text": "文本", "table": "表格", "image": "图片"}[element_type]
    loc = f"{src} · P{page}·{type_cn}"
```

> 🎯 **向后兼容的关键**：md/txt 文档没有 page/element_type metadata，走旧路径格式完全不变。只有 PDF 多模态解析的 chunk 才走新路径。现有 79 个测试零修改。

### 新增 `citation.py`

`Citation` 三级模型 + `clip_region`（区域裁剪）+ `build_citation`（从 metadata 构造）。

### service.py sources_payload（L05 已加）

sources 事件已带 `element_type`/`page`（L05 落地），L06 复用。

---

## 6. 本课代码会做什么

### `code.py`（纯本地）
- ① 引用三级展示：text → page → region
- ② 区域裁剪图：真裁剪毒文档 P4 表格区域为 PNG
- ③ 多模态引用进上下文：build_context 的新旧格式对比
- ④ 防幻觉强化：数字必须给出处，给不出拒答

### 落地到 kb-qa
- `generate.py` build_context：引用格式按 page/element_type 升级（向后兼容）
- 新增 `src/kb_qa/citation.py`：Citation + clip_region + build_citation
- `tests/test_citation.py`：13 个测试（三级引用 + 裁剪 + 格式回归 + guardrails 不误伤）

---

## 7. 跑起来

### 教学代码（纯本地）
```bash
cd doc-intelligence-lessons/06_citation
python code.py
```
预期：三级引用展示、P4 表格区域裁剪图生成（26KB PNG）、防幻觉纪律。

### 落地验证（kb-qa）
```bash
cd portfolio-projects/knowledge-base-qa
python -m pytest tests/test_citation.py -q             # 13 passed
python -m pytest tests/test_guardrails.py -q            # guardrails 不误伤新引用
python -m pytest -q                                      # 137 passed
```

### 验收检查
- [ ] 表格题答案引用形如「briefing.pdf · P4·表格」
- [ ] 区域裁剪图与原区域一致（P4 表格区域）
- [ ] guardrails 输出过滤不误伤新引用格式（test_guardrails 全绿）
- [ ] md/txt 文档引用格式不变（test_generate 回归）
- [ ] 防幻觉：数字无出处时答「材料中未找到」

---

## 🎯 面试话术

> 「我的作品集有可信度三部曲：数字可复算（代码解释器）、来源可回访（浏览器证据链）、引用可回溯（页码+区域截图）。多模态材料都是转换的产物——表格抽取、VLM 读图、OCR 识别——转换就会错，所以引用必须能一键回到原始位置核对。我的引用分三级：纯文字（旧）、页码（默认，零成本）、区域截图（最可信，PyMuPDF 裁剪原图）。bbox 从 L01 解析时全程携带到 L06 裁剪，链路不断。防幻觉纪律：数字给不出出处就拒答，绝不让转换错误被放大。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/kb_qa/citation.py` | **新增**：`Citation`（三级）+ `clip_region`（裁剪）+ `build_citation` | `python -c "from kb_qa.citation import clip_region; print('ok')"` |
| `src/kb_qa/generate.py` | `build_context` 引用格式按 page/element_type 升级（向后兼容） | `pytest tests/test_generate.py -q`（旧格式不变） |
| `tests/test_citation.py` | **新增**：13 个测试（三级引用 + 裁剪 + 格式回归 + guardrails） | `pytest tests/test_citation.py -q` → 13 passed |

> 📌 **两条主线位置**：本课是**溯源主线**的收尾——Element 的 page/bbox（L01 起）终于变成用户可见的「页码+区域」引用，可信度三部曲第三步完成；在**成本-精度主线**上，引用三级是按需升级（page 零成本、region 才生成裁剪图），不为默认场景强加成本。

下一课 [Lesson 07 — 语音入口（尝鲜）](../07_voice/) 跑通「语音问答」全链路——ASR → kb-qa → TTS，理解语音是入口不是核心。
