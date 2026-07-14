# Lesson 09 练习

> 本课是毕业整合课，练习侧重「全链路验证」和「生产就绪检查」。运行 `python code.py` 看端到端验收，然后过一遍检查清单。

---

## 练习 1：全开关端到端跑一遍，验证五层链路

跑 `code.py`，确认五层架构每层都有产出：

```bash
cd doc-intelligence-lessons/09_capstone
python code.py
```

逐项核对：
- [ ] P3 扫描页 OCR 填充（content 非空，含「试用期3个月」）
- [ ] P4 表格页 markdown 结构化（content 含 `|` 分隔）
- [ ] P5 图表页有 image 元素（待 VLM 描述）
- [ ] 引用带页码「company_briefing.pdf · P4·表格」
- [ ] 区域裁剪图生成（region 级引用）

**思考**：如果某一层断了（比如 OCR 没开），下游会怎样？——扫描页 content 为空，表格题答不出（信息没进库）。**五层链路任何一层断，对应题类就挂**。这就是为什么每课都要跑 before/after 验证——确保链路不断。

---

## 练习 2：生产就绪检查清单

对照下面的检查清单，逐项确认 kb-qa v3 的生产就绪度：

```
配置层
  [ ] 所有多模态开关默认关闭（enable_multimodal_ingest/ocr_engine/enable_image_caption/enable_voice）
  [ ] 开关 off 时行为同升级前（79 原始测试全绿）
  [ ] .env.example 有新增开关的说明

解析层（L01-L02）
  [ ] parse_pdf 对毒文档产出三类元素（text/table/image）
  [ ] 表格元素 content 是 markdown（非串行）
  [ ] 元素带 page + bbox（L06 溯源用）

理解层（L03-L04）
  [ ] OCR 开启时扫描页 content 非空
  [ ] 图表描述有缓存去重（重复入库不重复调 VLM）
  [ ] VLM 无 key 时走 mock 不崩

索引层（L05）
  [ ] 图片描述进 Chroma（element_type=image）
  [ ] sources 事件带 element_type/page

生成层（L05-L06）
  [ ] 引用格式带页码（PDF 文档）
  [ ] md/txt 文档引用格式不变（向后兼容）
  [ ] guardrails 不误伤新引用格式

评估层（L08）
  [ ] 收益表：三类杀手题 0→100%，纯文本 100%
  [ ] ragas 盲区诚实标注

入口层（L07）
  [ ] enable_voice=off 时 /api/ask_voice 返 404
```

**思考**：哪几项你还不确定？不确定的去对应课的 code.py 跑一遍验证。**生产就绪不是「能跑」，是「每个开关有确定的行为 + 降级路径 + 测试覆盖」**。

---

## 练习 3（设计实验）：构造你自己的多模态验收文档

拿一份你工作/学习里的真实 PDF（脱敏后），用本课的 `code.py` 改造跑一遍：

```python
# code.py 里把 POISON_PDF 换成你的文档
POISON_PDF = Path("你的文档.pdf")
```

跑 `code.py`，看：
- 哪些页被判为扫描/表格/图表？
- OCR 识别率如何？（对照原文人工核对）
- 表格抽取结构对不对？

**思考**：你的真实文档和毒文档的表现差异在哪？——真实文档的扫描质量、表格复杂度、图表类型可能不同。**这个差异就是你落地时的调参依据**：OCR 阈值要不要调、表格用 markdown 还是 HTML、哪些图值得 VLM 描述。把差异记录下来，这是你向团队汇报「多模态升级在我们数据上的表现」的素材。

---

## 练习 4（进阶）：写一份「v3 上线 Runbook」

给运维写一份 kb-qa v3 的上线操作手册（Runbook）：

```markdown
# kb-qa v3 上线 Runbook

## 启用多模态（按需）
1. .env 配 ENABLE_MULTIMODAL_INGEST=true
2. .env 配 OCR_ENGINE=hybrid（推荐置信度路由）
3. .env 配 ENABLE_IMAGE_CAPTION=true（图表多才开）
4. 重新 ingest：python cli.py ingest

## 降级（出问题时）
- OCR 误识别多：OCR_ENGINE=off（回退抽空）
- VLM 成本高：ENABLE_IMAGE_CAPTION=false（图表不入库）
- 全部回退：ENABLE_MULTIMODAL_INGEST=false（纯文本模式）

## 监控
- ingest 耗时（多模态比纯文本慢，OCR/VLM 有成本）
- 缓存命中率（vision_cache，重复入库应命中）
- 收益表定期跑（eval/run_multimodal_eval.py）
```

**思考**：Runbook 的核心是「出问题怎么办」——每个开关的降级路径、每个指标的告警阈值。**生产系统不是「能跑就行」，是「坏了能修、修了能验证」**。这份 Runbook 就是你对运维同事的承诺。

---

## ✅ 完成本课后，你应该能回答

1. kb-qa 经历了哪三个版本？每个版本加了什么？
2. 五层架构（解析/理解/索引/生成/溯源）各对应哪些课？
3. 所有开关默认关闭的意义？（向后兼容，不伤老能力）
4. 全仓课程为什么重编号？本课为什么是课程六？
5. 收益表的核心数字？（三类杀手题 0→100%，纯文本 100%）
6. 生产就绪的标准是什么？（开关确定 + 降级路径 + 测试覆盖）
7. 多模态升级在你自己的数据上要调什么？（OCR 阈值/表格格式/图表描述策略）
