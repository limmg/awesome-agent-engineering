# Lesson 06 练习

> 改 `code.py` 和 `src/kb_qa/citation.py` 里的代码，运行 `python code.py` 观察变化。本课依赖 PyMuPDF（venv 已装），毒文档在 `data/multimodal_docs/`。

---

## 练习 1：裁剪不同区域，验证 bbox 精度

`code.py` 演示 2 裁剪的是 P4 表格区域（50,80,545,280）。改成裁剪更小的区域——只裁「P5 那一行」：

```python
# code.py show_region_clip 里，bbox 改成 P5 行的范围
# P5 在表格第 3 数据行，y 坐标大约 200-228（见 generate_poison_pdf 的 data_y）
bbox = (50, 195, 545, 230)   # 只裁 P5 那一行
out = clip_region(POISON_PDF, page=4, bbox=bbox, dpi=150)
```

跑 `code.py`，看裁剪图变成了什么。

**思考**：裁剪图现在只有 P5 那一行（P5 | 22000 | 6000 | 1.0-1.5）。这就是 **region 级引用的精度价值**——用户问「P5 基本工资」，裁剪图直接框出那一行，不用翻整页。bbox 越精确，核对成本越低。L01 练习 3 量过「block 级 bbox vs 整页 bbox」的面积比——region 引用把那个比变成了用户体验。

---

## 练习 2：调 dpi，平衡裁剪图清晰度和文件大小

`clip_region` 默认 dpi=150。调成 300（高清）和 72（低清）对比：

```python
# 三档 dpi
for dpi in [72, 150, 300]:
    out = clip_region(POISON_PDF, page=4, bbox=(50,80,545,280), dpi=dpi)
    print(f"dpi={dpi}: {out.stat().st_size/1024:.0f}KB")
```

**思考**：dpi 72 的裁剪图可能模糊到看不清数字，dpi 300 的清晰但文件大 4 倍。**region 引用的 dpi 要够用户看清数字**——薪酬表的数字小，至少 150dpi；图表的柱子大，72dpi 够。这就是为什么 clip_region 把 dpi 做成参数——按内容类型调。

---

## 练习 3（设计实验）：量「三级引用」的用户核对成本

这是本课的**设计实验验证**题——量化引用精度对用户核对成本的影响。

设计一个对照：同一个问题「P5 基本工资多少」，三种引用级别下用户核对要多久/多费力：

```python
# 模拟用户核对流程
levels = {
    "text": "答案来自 briefing.pdf",                          # 用户要翻整个文档找
    "page": "答案来自 briefing.pdf · P4·表格",                  # 用户翻到 P4 找表格
    "region": "答案来自 briefing.pdf · P4·表格 + [裁剪图]",     # 用户直接看裁剪图
}
```

**思考**：估算每种级别用户核对所需时间：
- text：打开 PDF → 搜索 → 翻页找表格 → 找 P5 行（~30s+）
- page：翻到 P4 → 找 P5 行（~10s）
- region：看裁剪图（~2s）

**这个时间差就是引用升级的用户价值**。把三个数字记下来——这是「引用可回溯」的产品论证。如果你做的是企业合规系统（数字必须可审计），region 级几乎必须；如果是内部 FAQ，page 级够用。

---

## 练习 4（进阶）：实现「自动 region 升级」策略

不是所有引用都需要 region，但有些场景应该自动升级。实现一个智能策略：

```python
# citation.py 加一个函数
def should_upgrade_to_region(question: str, element_type: str) -> bool:
    """判断是否该自动升级到 region 级引用。"""
    # 数字类问题 + table/image 元素 → 升级（数字需精确核对）
    has_number = any(c.isdigit() for c in question)
    is_numeric_element = element_type in ("table", "image")
    return has_number and is_numeric_element

# service.py 里：检索后判断是否升级
for doc in docs:
    if should_upgrade_to_region(question, doc.metadata.get("element_type", "text")):
        citation = build_citation(..., enable_clip=True)   # 自动裁剪
    else:
        citation = build_citation(..., enable_clip=False)  # page 级
```

**思考**：自动升级的触发条件怎么定？——**数字类问题 + 多模态元素**最需要 region（数字要精确核对）。纯文本问题不需要（没有「原图」可裁）。这个策略让 region 只花在刀刃上——大部分引用走 page 级（免费），数字题才自动升级（花钱但值得）。这就是成本-精度主线在引用层的体现。

---

## ✅ 完成本课后，你应该能回答

1. 为什么多模态下旧引用（source · section）不够？（转换产物无法核对具体位置）
2. 引用三级（text/page/region）的精度和代价分别是什么？默认用哪级？
3. 区域裁剪图的 bbox 从哪来？（L01 Element.bbox 全程携带）
4. 可信度三部曲是哪三部？本课在哪一步？（可复算/可回访/可回溯）
5. 防幻觉纪律：数字类答案无出处时该怎么办？（拒答，不编造）
6. generate.build_context 怎么保证 md/txt 文档引用格式不变？（page/element_type 缺失走旧路径）
7. （落地）kb-qa 的 Citation 模型有哪几个字段？clip_region 用什么库裁剪？
