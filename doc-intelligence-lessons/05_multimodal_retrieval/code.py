"""Lesson 05 — 多模态检索：图片怎么被搜到
==================================================
打通「文字 query 检索到图片元素」的链路。三种流派对照：
    ① 描述索引（本课主路线）：图→VLM 文字描述→embedding 入同一个 Chroma
    ② CLIP 双塔（可选实验）：图文同空间，免 VLM 但多一套本地模型栈
    ③ 整页截图直检：逐页 VLM 扫描，只适合评估不适合生产

演示用 BM25/字符重叠近似检索（无需真 embedding，离线可跑），展示「描述索引让图表可被搜到」。
有 API key 时可用真 embedding-3 演示。

运行：python code.py
依赖：PyMuPDF（venv 已装）；毒文档 data/multimodal_docs/
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows GBK 坑：中文输出会 UnicodeEncodeError，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
POISON_PDF = ROOT / "data" / "multimodal_docs" / "company_briefing.pdf"
sys.path.insert(0, str(ROOT / "portfolio-projects" / "knowledge-base-qa" / "src"))


# ══════════════════════════════════════════════════════════════════
# 1. 构造「语料库」：模拟 ingest 后 Chroma 里的文档
#    每条带 element_type，描述索引把图表描述也纳入
# ══════════════════════════════════════════════════════════════════
def build_corpus() -> list[dict]:
    """模拟 ingest 后的向量库内容。text-only vs +描述索引 两种。"""
    # 共用的文本块（L01 抽出的 text 元素）
    text_blocks = [
        {"content": "公司专注于企业级 AI 解决方案，现有员工约 500 人。", "type": "text", "page": 1, "source": "briefing"},
        {"content": "标准工作时间：9:00 - 18:00，午休 1 小时。", "type": "text", "page": 2, "source": "briefing"},
        {"content": "入职满 3 年不满 5 年：每年 10 天年假。", "type": "text", "page": 2, "source": "briefing"},
    ]
    # 图表页文本层抽到的（只有标题，无数值）
    chart_text = "2024 年度经营数据 上图为本年度各季度营收"
    # L04 生成的图表描述（含数值）
    chart_desc = (
        "图表类型：柱状图 标题：2024 年度季度营收（万元）"
        "数值：Q1:1800 Q2:2400 Q3:2100 Q4:2900"
        "趋势：Q4 最高 2900，Q2 到 Q3 下降"
    )
    # 薪酬表 markdown（L02 抽出）
    table_md = "职级 基本工资 岗位津贴 P3 12000 3000 P4 16000 4000 P5 22000 6000"

    return {
        "text-only（无描述索引）": [
            *text_blocks,
            {"content": chart_text, "type": "text", "page": 5, "source": "briefing"},  # 图表页只有标题
            {"content": table_md, "type": "table", "page": 4, "source": "briefing"},
        ],
        "+描述索引（L04 描述入库）": [
            *text_blocks,
            {"content": chart_text, "type": "text", "page": 5, "source": "briefing"},
            # 图表描述作为 image 元素入库（element_type=image）
            {"content": chart_desc, "type": "image", "page": 5, "source": "briefing"},
            {"content": table_md, "type": "table", "page": 4, "source": "briefing"},
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 2. 近似检索：用 BM25 风格的字符重叠排序（无需真 embedding）
#    真检索用 embedding-3，这里用重叠近似演示「描述索引的价值」
# ══════════════════════════════════════════════════════════════════
def _tokenize(text: str) -> set[str]:
    """极简分词：按非字母数字切，取长度≥2 的片段（中文逐字 + 英文词）。"""
    import re
    tokens = set(re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fa5]", text))
    return {t.lower() for t in tokens if len(t) >= 1}


def retrieve(corpus: list[dict], query: str, top_k: int = 3) -> list[dict]:
    """近似检索：query 与每条文档的 token 重叠数排序。"""
    q_tokens = _tokenize(query)
    scored = []
    for doc in corpus:
        d_tokens = _tokenize(doc["content"])
        overlap = len(q_tokens & d_tokens)
        scored.append((overlap, doc))
    scored.sort(key=lambda x: -x[0])
    return [
        {"score": s, **{k: v for k, v in d.items() if k != "content"}, "preview": d["content"][:60]}
        for s, d in scored[:top_k]
    ]


# ══════════════════════════════════════════════════════════════════
# 3. 路由演示：命中 image 元素 → 触发现场看图
# ══════════════════════════════════════════════════════════════════
def route_by_type(top_doc: dict) -> str:
    """按 element_type 路由（L04/L05 的生成层逻辑）。"""
    etype = top_doc.get("type", "text")
    if etype == "image":
        return "现场看图（answer_with_image）：命中图表，调 VLM 看原图作答"
    elif etype == "table":
        return "结构化作答：命中表格，markdown/HTML 进 prompt"
    else:
        return "文本直答（stream_answer）：走老路"


# ══════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════
def main() -> None:
    corpora = build_corpus()

    print("=" * 70)
    print("演示 1：图表题的检索 —— text-only vs +描述索引")
    print("=" * 70)
    chart_queries = [
        "Q3 的营收是多少万元",
        "哪个季度营收最高",
        "季度营收趋势",
    ]
    for q in chart_queries:
        print(f"\n  query: 「{q}」")
        for name, corpus in corpora.items():
            results = retrieve(corpus, q, top_k=1)
            top = results[0]
            etype = top.get("type", "text")
            hit = "✅ 命中图表描述" if etype == "image" else ("🟡 命中图表标题(无数值)" if top["page"] == 5 else "🚫 命中无关文本")
            print(f"    {name:<22} → top1: P{top.get('page','?')} [{etype:<5}] score={top['score']} {hit}")

    print("\n" + "=" * 70)
    print("演示 2：检索结果路由 —— 命中 image 触发现场看图")
    print("=" * 70)
    # 用 +描述索引 的语料，演示三种 query 的路由
    routed_corpus = corpora["+描述索引（L04 描述入库）"]
    test_cases = [
        ("Q3 营收多少", "图表题"),
        ("P5 基本工资多少", "表格题"),
        ("年假几天", "纯文本题"),
    ]
    print(f"\n{'query':<18} {'命中类型':<10} {'路由动作'}")
    print("-" * 70)
    for q, label in test_cases:
        top = retrieve(routed_corpus, q, top_k=1)[0]
        action = route_by_type(top)
        print(f"{q:<16} {top.get('type','text'):<10} {action}")

    print("\n> 🎯 统一库 + metadata 区分 element_type，命中后按类型路由：")
    print("  image → 现场看图（L04）、table → 结构化作答（L02）、text → 文本直答（老路）")

    print("\n" + "=" * 70)
    print("演示 3：CLIP 双塔 vs 描述索引（方案对比）")
    print("=" * 70)
    print("""
  方案          原理                    VLM费用   本地模型    检索精度
  ─────────────────────────────────────────────────────────────────
  描述索引       图→VLM描述→embedding    有(入库)   无          ✅ 高
  (本课主路线)                           一次性                 描述含语义

  CLIP双塔       图文同空间，免描述      无        有(torch)   🟡 中
  (可选实验)                              但是模型栈重，中文依赖chinese-clip

  整页截图直检   逐页VLM扫描            有(每页)   无          🟡 低
  (只适合评估)                            太贵                    不适合生产
  """)
    print("  本课选描述索引：与现有 Chroma 无缝（描述就是文本）、VLM 费用入库时一次性、")
    print("  精度取决于描述质量（L04 已保证结构化）。CLIP 省了 VLM 但多一套模型栈。")

    print("\n" + "=" * 70)
    print("诚实标注")
    print("=" * 70)
    print("  - 检索用 token 重叠近似（非真 embedding-3），演示「描述让图表可搜」。")
    print("  - 真检索需 API key 跑 embedding-3 + Chroma，本课用近似够说明量级。")
    print("  - CLIP 双塔未真跑（需 torch + chinese-clip，安装重），只讲定位与取舍。")
    print("  - service.py 的 sources 事件已带 element_type/page（L05 落地），前端可按类型展示。")


if __name__ == "__main__":
    main()
