# Lesson 05 练习

> 改 `code.py` 里的代码，运行 `python code.py` 观察变化。本课近似检索（token 重叠），无需真 embedding。

---

## 练习 1：调描述质量，观察检索 score 变化

`code.py` 的 `build_corpus` 里图表描述是预录的（含 Q1-Q4 数值）。改成「废话描述」看检索变化：

```python
# build_corpus 里，chart_desc 改成废话版
chart_desc = "这是一张关于营收的图表"   # 废话：无数值无标签
```

跑 `code.py` 演示 1，看图表题的检索 score 变化。

**思考**：废话描述的 score 降了多少？还能命中图表题吗？——**描述质量直接决定检索质量**。废话描述（「这是一张图表」）和图表标题（「2024 年度经营数据」）检索效果差不多，都答不出数值。这就是 L04 强调「prompt 要结构化（数值/标签/趋势）」的原因——**描述是检索的锚点，锚点没数值，检索再准也答不出。**

---

## 练习 2：构造一个「图文都相关」的 query，看路由行为

现在路由只看 top1 的 element_type。构造一个图文都能答的 query：

```python
# code.py 演示 2 加一个测试 case
test_cases = [
    ("Q3 营收多少", "图表题"),
    ("P5 基本工资多少", "表格题"),
    ("年假几天", "纯文本题"),
    ("2024 年度经营情况怎么样", "图文都相关"),  # 新增：标题和图表都沾边
]
```

跑 `code.py`，看这个 query 路由到哪个类型。

**思考**：图文都相关的 query，top1 是 text（标题）还是 image（描述）？——**取决于谁的 score 高**。如果标题 score 高，走文本直答（但答不出数值）；如果描述 score 高，走现场看图（能答）。**这就是统一库 + rerank 的价值**：让最相关的元素排第一，不管它是什么类型。rerank（ops 课已实现）在这里起到「跨类型排序」的作用。

---

## 练习 3（设计实验）：量「描述索引 vs 无」的检索召回率差

这是本课的**设计实验验证**题——量化描述索引对图表题召回的影响。

在 `code.py` 里，对 4 道图表题（CHT01-04）跑两套语料（text-only vs +描述索引），统计「图表题是否命中含数值的文档」：

```python
# code.py 加一个统计函数
chart_questions = ["Q1营收", "Q3营收", "Q4营收", "哪个季度最高"]
for name, corpus in corpora.items():
    hits = 0
    for q in chart_questions:
        top = retrieve(corpus, q, top_k=1)[0]
        # 命中含数值的文档算成功
        if any(v in top["preview"] for v in ["1800","2400","2100","2900"]):
            hits += 1
    print(f"{name}: 图表题召回 {hits}/4")
```

**思考**：text-only 的召回是多少？（大概率 0/4——标题没数值）+描述索引呢？（应该 4/4——描述含数值）。**这个召回率差就是描述索引的收益证据**。真 embedding 的效果更好（语义匹配），token 重叠是下限。把这个数字记下来，L08 的收益表要用。

---

## 练习 4（进阶）：实现 element_type 过滤的检索

现在检索返回所有类型混排。实现「只检索图表」的过滤模式：

```python
# retriever.py 加一个过滤方法
def retrieve_by_type(self, question, mode=None, element_type=None):
    """检索 + 按 element_type 过滤（可选）。"""
    docs = self.retrieve(question, mode)
    if element_type:
        docs = [d for d in docs if d.metadata.get("element_type") == element_type]
    return docs
```

**思考**：什么时候需要按类型过滤？——**用户明确问图表时**（「看一下营收图表」）可以只搜 image 元素，减少噪声。但大多数场景不该过滤——**用户不知道答案在哪种类型里**，统一检索 + rerank 排序更自然。过滤是特殊需求（如「只搜表格」的专项查询），不是默认行为。这就是为什么本课选「统一库 + 路由」而非「分库」。

---

## ✅ 完成本课后，你应该能回答

1. 图片为什么不能直接被 embedding 检索？描述索引怎么解决？
2. 描述索引 vs CLIP 双塔 vs 整页截图，各自的成本/精度/架构摩擦？
3. 为什么选描述索引？（零架构改动 + VLM 入库一次性 + 精度取决于描述质量）
4. 统一库 vs 分库的取舍？为什么选统一库 + metadata 路由？
5. 检索结果按 element_type 路由：image/table/text 分别走什么生成路径？
6. service.py 的 sources 事件现在带哪些多模态字段？给谁用？
7. （落地）kb-qa 的图表描述怎么进 Chroma？metadata 带什么？
