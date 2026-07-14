"""毒文档生成器：构造一份「混合 PDF」用于多模态文档智能课程的试金石。

产物：company_briefing.pdf —— 「云启科技制度与经营简报」，6 页，含四类杀手页：
    ① 纯文本页（公司简介 / 考勤制度）        —— 基线应该答对（对照）
    ② 扫描页（保密与竞业协议）                —— 文字渲染成图片嵌入，无文本层
    ③ 复杂表格（薪酬等级表，含合并表头单元格）—— 有文本层但被拍平成串行乱序文字
    ④ 图表页（季度营收柱状图）                —— 数字只在 matplotlib 生成的图片里
    ⑤ 图文混排页（培训与发展）                —— 正文 + 嵌入的晋升阶梯示意图

复现：python generate_poison_pdf.py
依赖：PyMuPDF(fitz) + matplotlib + Pillow（venv 已装）；中文字体用系统 msyh/simhei
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows GBK 坑：脚本输出中文会 UnicodeEncodeError，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import fitz  # PyMuPDF
import matplotlib
matplotlib.use("Agg")  # 无头模式，不弹窗
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
OUT_PDF = HERE / "company_briefing.pdf"

# ── 中文字体：matplotlib 需要显式注册系统 TTF，否则画图全是方框 ──────────────
# 注意：msyh.ttc 是 TrueType 集合，addfont 读不了；用单文件 simhei.ttf 最稳。
_SIMHEI = r"C:/Windows/Fonts/simhei.ttf"
_CN_FONT_PROP = None
if Path(_SIMHEI).exists():
    font_manager.fontManager.addfont(_SIMHEI)
    _CN_FONT_PROP = font_manager.FontProperties(fname=_SIMHEI)
    plt.rcParams["font.sans-serif"] = [_CN_FONT_PROP.get_name()]
    plt.rcParams["axes.unicode_minus"] = False  # 负号显示
else:
    print("[WARN] 未找到 simhei.ttf，图表中文将显示为方框（安装 SimHei 或换系统字体）")


# ══════════════════════════════════════════════════════════════════
# 1. 通用：写一页纯文本（带标题），文本层正常
# ══════════════════════════════════════════════════════════════════
def write_text_page(doc: fitz.Document, title: str, lines: list[str]) -> fitz.Page:
    """写一页有正常文本层的页面。返回该 page。"""
    page = doc.new_page(width=595, height=842)  # A4 纵向
    page.insert_text((50, 55), title, fontname="china-s", fontsize=16, color=(0.1, 0.2, 0.5))
    # 标题下划线
    page.draw_line(fitz.Point(50, 62), fitz.Point(545, 62), color=(0.5, 0.5, 0.5), width=0.8)
    y = 90
    for line in lines:
        page.insert_text((50, y), line, fontname="china-s", fontsize=11, color=(0, 0, 0))
        y += 22
    return page


# ══════════════════════════════════════════════════════════════════
# 2. 扫描页：先在临时文档里排好文字 → 渲染成 pixmap → 整页嵌入图片（无文本层）
# ══════════════════════════════════════════════════════════════════
def make_scan_page(doc: fitz.Document, title: str, lines: list[str]) -> fitz.Page:
    """模拟扫描件：文字渲染成位图后整页插入，抽取时文本量≈0。"""
    tmp = fitz.open()
    src = tmp.new_page(width=595, height=842)
    src.insert_text((50, 55), title, fontname="china-s", fontsize=16, color=(0.1, 0.2, 0.5))
    src.draw_line(fitz.Point(50, 62), fitz.Point(545, 62), color=(0.4, 0.4, 0.4), width=0.8)
    y = 90
    for line in lines:
        src.insert_text((50, y), line, fontname="china-s", fontsize=11, color=(0, 0, 0))
        y += 22
    # 渲染成 150dpi 位图（模拟扫描质量）
    pix = src.get_pixmap(dpi=150)
    tmp.close()
    # 新页面只插图片 —— 这就是「无文本层」的扫描页
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(0, 0, 595, 842), pixmap=pix)
    return page


# ══════════════════════════════════════════════════════════════════
# 3. 表格页：手绘表格（有文本层，但 get_text 会拍平成乱序串行文字）
# ══════════════════════════════════════════════════════════════════
def make_table_page(doc: fitz.Document) -> fitz.Page:
    """薪酬等级表：合并表头 + 4 行数据。有文本层但抽取后结构丢失。"""
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 55), "薪酬等级表（2024 版）", fontname="china-s", fontsize=16, color=(0.1, 0.2, 0.5))
    page.draw_line(fitz.Point(50, 62), fitz.Point(545, 62), color=(0.5, 0.5, 0.5), width=0.8)

    # 表格几何：x 列边界，y 行边界
    xs = [50, 150, 290, 430, 545]
    # 合并表头：第 1 行「职级」跨 1 列，「薪酬（元/月）」跨 2 列，「绩效」跨 2 列
    head1_y = [95, 125]
    # 第 2 行子表头
    head2_y = [125, 150]
    # 数据 4 行
    data_y = [150, 178, 206, 234, 262]

    rows_y = head1_y + [150] + [178, 206, 234, 262]  # 所有横线

    # 画横线
    for ry in [95, 125, 150, 178, 206, 234, 262]:
        page.draw_line(fitz.Point(xs[0], ry), fitz.Point(xs[-1], ry), color=(0, 0, 0), width=0.7)
    # 画竖线（注意合并单元格处不画）
    for x in xs:
        page.draw_line(fitz.Point(x, 95), fitz.Point(x, 262), color=(0, 0, 0), width=0.7)

    # ── 合并表头第 1 行 ──
    page.insert_text((78, 115), "职级", fontname="china-s", fontsize=10)
    page.insert_text((185, 115), "薪酬（元/月）", fontname="china-s", fontsize=10)
    page.insert_text((448, 115), "绩效系数", fontname="china-s", fontsize=10)

    # ── 子表头第 2 行 ──
    page.insert_text((175, 143), "基本工资", fontname="china-s", fontsize=9)
    page.insert_text((315, 143), "岗位津贴", fontname="china-s", fontsize=9)
    page.insert_text((455, 143), "范围", fontname="china-s", fontsize=9)

    # ── 数据行 ──
    table_data = [
        ("P3", "12000", "3000", "0.8 - 1.2"),
        ("P4", "16000", "4000", "0.9 - 1.3"),
        ("P5", "22000", "6000", "1.0 - 1.5"),
        ("P6", "30000", "8000", "1.1 - 1.6"),
    ]
    for i, (level, base, allow, perf) in enumerate(table_data):
        ry = data_y[i] + 20
        page.insert_text((80, ry), level, fontname="china-s", fontsize=10)
        page.insert_text((180, ry), base, fontname="china-s", fontsize=10)
        page.insert_text((320, ry), allow, fontname="china-s", fontsize=10)
        page.insert_text((455, ry), perf, fontname="china-s", fontsize=10)

    page.insert_text((50, 290), "注：试用期工资为转正后基本工资的 80%，见保密协议扫描页。", fontname="china-s", fontsize=9, color=(0.4, 0.4, 0.4))
    return page


# ══════════════════════════════════════════════════════════════════
# 4. 图表页：matplotlib 画柱状图 → 嵌入（数字只在图里，无文本层）
# ══════════════════════════════════════════════════════════════════
def make_chart_page(doc: fitz.Document) -> fitz.Page:
    """季度营收柱状图：数值标签画在图里，PDF 页面无对应文本层。"""
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    revenue = [1800, 2400, 2100, 2900]  # 万元

    fp = _CN_FONT_PROP
    fig, ax = plt.subplots(figsize=(7, 3.8))
    bars = ax.bar(quarters, revenue, color=["#4C72B0", "#55A868", "#C44E52", "#8172B2"], width=0.55)
    ax.set_title("2024 年度季度营收（万元）", fontsize=13, fontproperties=fp)
    ax.set_ylabel("营收（万元）", fontproperties=fp)
    ax.set_xticks(range(len(quarters)))
    ax.set_xticklabels(quarters, fontproperties=fp)
    ax.set_ylim(0, 3400)
    # 每根柱子顶部标数值（这就是「只在图里的数字」）
    for bar, val in zip(bars, revenue):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 60, str(val), ha="center", fontsize=11, fontproperties=fp)
    fig.tight_layout()
    chart_png = HERE / "_chart_revenue.png"
    fig.savefig(chart_png, dpi=150)
    plt.close(fig)

    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 55), "2024 年度经营数据", fontname="china-s", fontsize=16, color=(0.1, 0.2, 0.5))
    page.draw_line(fitz.Point(50, 62), fitz.Point(545, 62), color=(0.5, 0.5, 0.5), width=0.8)
    page.insert_image(fitz.Rect(60, 80, 535, 460), filename=str(chart_png))
    page.insert_text((50, 490), "上图为本年度各季度营收，数据以图表为准。", fontname="china-s", fontsize=10, color=(0.3, 0.3, 0.3))
    return page


# ══════════════════════════════════════════════════════════════════
# 5. 图文混排页：正文 + 嵌入一张晋升阶梯示意图
# ══════════════════════════════════════════════════════════════════
def make_mixed_page(doc: fitz.Document) -> fitz.Page:
    """图文混排：左侧文字说明，右侧嵌入晋升阶梯流程图。"""
    # 先画右侧的晋升阶梯图
    fp = _CN_FONT_PROP
    fig, ax = plt.subplots(figsize=(3.2, 3.5))
    levels = ["P6\n高级专家", "P5\n资深", "P4\n中级", "P3\n初级"]
    colors = ["#8172B2", "#55A868", "#4C72B0", "#C44E52"]
    for i, (lv, c) in enumerate(zip(levels, colors)):
        ax.barh(i, 1, color=c)
        ax.text(0.5, i, lv, ha="center", va="center", color="white", fontsize=10, fontproperties=fp)
        if i < len(levels) - 1:
            ax.annotate("", xy=(0.5, i - 0.6), xytext=(0.5, i - 0.4), arrowprops=dict(arrowstyle="->", lw=1.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, len(levels) - 0.4)
    ax.set_title("晋升阶梯", fontsize=11, fontproperties=fp)
    ax.axis("off")
    fig.tight_layout()
    ladder_png = HERE / "_chart_ladder.png"
    fig.savefig(ladder_png, dpi=150)
    plt.close(fig)

    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 55), "培训与发展", fontname="china-s", fontsize=16, color=(0.1, 0.2, 0.5))
    page.draw_line(fitz.Point(50, 62), fitz.Point(545, 62), color=(0.5, 0.5, 0.5), width=0.8)

    left_lines = [
        "公司为员工提供完善的培训与发展体系：",
        "1. 新员工入职培训 5 个工作日，涵盖公司文化与制度。",
        "2. 每位员工每年享有 40 小时带薪培训时间。",
        "3. 晋升评审每年 2 次，分别在 3 月和 9 月。",
        "4. 连续两次绩效 A 的员工可破格晋升。",
        "",
        "晋升路径见右侧示意图，从 P3 到 P6",
        "逐级晋升，每级需满足绩效与年限要求。",
    ]
    y = 90
    for line in left_lines:
        page.insert_text((50, y), line, fontname="china-s", fontsize=11)
        y += 22

    # 右侧嵌入图片
    page.insert_image(fitz.Rect(360, 90, 540, 430), filename=str(ladder_png))
    return page


# ══════════════════════════════════════════════════════════════════
# 主流程：组装 6 页 PDF
# ══════════════════════════════════════════════════════════════════
def build_pdf(out_path: Path = OUT_PDF) -> Path:
    doc = fitz.open()

    # P1 公司简介（纯文本）
    write_text_page(doc, "云启科技制度与经营简报", [
        "云启科技成立于 2018 年，总部位于上海张江高科技园区。",
        "公司专注于企业级 AI 解决方案，现有员工约 500 人。",
        "本文档汇总公司核心制度与 2024 年度经营数据，供全体员工查阅。",
        "",
        "本文档分六个部分：公司简介、考勤制度、保密协议、",
        "薪酬等级、经营数据、培训发展。",
        "",
        "如对内容有疑问，请联系人力资源部。",
    ])

    # P2 考勤与假勤制度（纯文本）
    write_text_page(doc, "考勤与假勤制度", [
        "标准工作时间：9:00 - 18:00，午休 1 小时。",
        "迟到 15 分钟以内不扣薪；超过 15 分钟按 50 元/次扣薪。",
        "当月迟到 3 次及以上，取消当月全勤奖。",
        "",
        "年假政策：",
        "  入职满 1 年：每年 5 天年假。",
        "  入职满 3 年不满 5 年：每年 10 天年假。",
        "  入职满 5 年及以上：每年 15 天年假。",
        "",
        "病假需提供医院证明，按基本工资的 70% 发放。",
    ])

    # P3 保密与竞业协议（扫描页 —— 无文本层！）
    make_scan_page(doc, "保密与竞业协议（扫描件）", [
        "本页为纸质文件扫描件，以下条款具有同等效力：",
        "",
        "一、试用期 3 个月，试用期工资为转正后基本工资的 80%。",
        "二、员工在职期间及离职后 2 年内，不得从事同业竞争业务。",
        "三、违反保密义务的，赔偿金额为年薪的 3 倍。",
        "四、离职需提前 30 天书面通知，并完成工作交接。",
        "",
        "（本页为扫描影像，文字以图像形式呈现）",
    ])

    # P4 薪酬等级表（复杂表格）
    make_table_page(doc)

    # P5 经营数据（图表页）
    make_chart_page(doc)

    # P6 培训与发展（图文混排）
    make_mixed_page(doc)

    doc.save(str(out_path))
    doc.close()
    return out_path


if __name__ == "__main__":
    pdf = build_pdf()
    print(f"[OK] 毒文档已生成：{pdf}")
    # 自检：逐页打印文本量，验证扫描页≈0
    check = fitz.open(str(pdf))
    for i, pg in enumerate(check):
        txt = pg.get_text().strip()
        imgs = pg.get_images()
        tag = ""
        if i == 2:
            tag = " ← 扫描页(预期文本≈0)"
        elif i == 3:
            tag = " ← 表格页(预期文本乱序)"
        elif i == 4:
            tag = " ← 图表页(预期数值不在文本)"
        print(f"  P{i+1}: 文本 {len(txt):4d} 字 | 图片 {len(imgs)} 张{tag}")
    check.close()
