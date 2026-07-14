# Lesson 01 练习

> 改 `code.py` 和 `src/kb_qa/doc_parser.py` 里的代码，运行 `python code.py` 观察变化。本课依赖 PyMuPDF（venv 已装），毒文档在 `data/multimodal_docs/`。

---

## 练习 1：调表格判定阈值，观察分类边界

`doc_parser.py` 顶部有个启发式阈值 `_TABLE_LINE_THRESHOLD = 6`——一页矢量线段超过 6 条就判表格。调一下看边界：

```python
# doc_parser.py
_TABLE_LINE_THRESHOLD = 6   # 改成 15
```

重新跑 `code.py`，看演示 1 的 P4（表格页，13 条线）判定变成什么。

**思考**：阈值改成 15 后，P4 还被判为 table 吗？（13 < 15，不再判表格，退化成 text）。这说明启发式阈值不是万能的——**真实文档里有的表格只有 4-5 条线（无边框表）会被漏判**。L02 会用 pdfplumber 的 `find_tables()` 做更可靠的表格检测（基于文本对齐，不只看线）。理解启发式的局限，是选型升级的前提。

---

## 练习 2：给扫描页加「低质文本」混合判定

现在的扫描页判定是「字符数=0 且有图」。但真实扫描件有时 OCR 引擎会塞进一些乱码字符（个位数），导致「字符数>0」漏判。加一个更鲁棒的判定：

```python
# doc_parser.py 的 parse_pdf 里，把扫描页判定改成：
if char_count < 10 and has_images:   # 原来：char_count == 0
    # 字符极少 + 有图 → 视为扫描页（容错 OCR 残留）
    ...
```

重新跑 `code.py`，观察 P3 的判定是否稳定（P3 是纯扫描，字符数=0，<10 也命中）。

**思考**：为什么阈值用 `< 10` 而不是 `< 50`？因为正常文本页哪怕最短的标题也有十几字，但 OCR 乱码通常只有零星几个字。这个阈值是**在「漏判扫描页」和「误判短文本页」之间的平衡**——太松会把正常页当扫描页（浪费 OCR）、太严会漏掉有残留字符的扫描页。**启发式没有完美解，只有适合你数据的权衡。**

---

## 练习 3（设计实验）：对比「block 级 bbox」vs「整页 bbox」的溯源精度

这是本课的**设计实验验证**题——量化 bbox 精度对引用溯源的价值。

现在纯文本页的 text 元素是按 `get_text("blocks")` 拆的，每个 block 有自己的 bbox。改成「整页一个 text 元素」对比：

```python
# doc_parser.py 的 parse_pdf，纯文本分支改成（临时）：
else:
    # 不按 block 拆，整页一个 text 元素
    if char_count > 0:
        elements.append(Element(
            type="text", content=page_text, page=page_num,
            bbox=_full_page_bbox(page), source=source   # 整页 bbox
        ))
```

跑 `code.py`，看演示 2 的 P1 元素数从 7 变成 1。

**思考**：两种拆法的区别在哪？——**bbox 精度**。block 级 bbox 能定位到「这一段话在页面的哪个矩形」，L06 裁剪引用时只裁这一小块；整页 bbox 只能说「在这页」，裁剪等于截整页。用毒文档的 P1 算一下：block 级 bbox 的面积总和 vs 整页面积，比值是多少？**这个比值就是「溯源能精确到多小区域」的量化指标。** 答案通常是整页面积的 10-20%——block 级让引用区域缩小了 5-10 倍。

---

## 练习 4（进阶）：用 page.get_text("dict") 拿 span 级 bbox

block 级 bbox 已经比整页精确，但还能更细——到 **span 级**（每个连续文字片段）。`get_text("dict")` 返回 block → line → span 的嵌套结构，每个 span 都带 bbox。

改写纯文本分支，用 dict 模式拿到 span：

```python
# doc_parser.py，纯文本分支：
d = page.get_text("dict")
for block in d["blocks"]:
    if block["type"] != 0:  # 只处理文本 block
        continue
    for line in block["lines"]:
        for span in line["spans"]:
            text = span["text"].strip()
            if text:
                elements.append(Element(
                    type="text", content=text, page=page_num,
                    bbox=tuple(span["bbox"]), source=source
                ))
```

跑 `code.py`，看 P1 的元素数——会比 block 级多得多（每行甚至每个词一个 span）。

**思考**：span 级更细，但一定更好吗？——**未必**。span 太细会导致：①元素数爆炸，向量库 chunk 过多 ②一个完整的句子被拆成多个 span，embedding 吃不到完整语义。**bbox 精度和检索质量是矛盾的**——block 级通常是平衡点（一段话一个元素，既有精确 bbox 又保语义）。这就是工程：没有银弹，只有权衡。L06 做区域引用时，block 级 bbox 够用且不过度。

---

## ✅ 完成本课后，你应该能回答

1. PDF 的三层结构是什么？为什么说「看得见字 ≠ 有文本层」？
2. 扫描页在三层结构里属于哪一层？为什么 `get_text()` 抽不到它？
3. 表格页的判定依据是什么？启发式阈值怎么定的？有什么局限？
4. Element 模型为什么要带 `type` 和 `bbox`？分别给后面哪课用？
5. 版面感知解析 vs 版面模型（MinerU），各自的成本-精度取舍？本课为什么选前者？
6. 为什么 `enable_multimodal_ingest` 默认关闭？开关 off 时 kb-qa 行为有什么变化？
7. （落地）kb-qa 的 `ingest_directory` 现在怎么按 suffix + 开关路由 PDF？空内容的 image 元素为什么此时不入库？
