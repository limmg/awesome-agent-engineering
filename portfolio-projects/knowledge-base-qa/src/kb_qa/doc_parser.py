"""版面感知 PDF 解析器：把 PDF 拆成带类型和坐标的 Element 流。

为什么需要它（L01 的核心认知）：
    现状 ingest 只走「文本抽取→切块」，对 PDF 用 get_text() 拿到的是一坨串行文字——
    扫描页抽到空、表格拍平丢结构、图表数值不可见（见 L00 基线）。
    本模块产出统一元素模型 Element(type, content, page, bbox)，让下游能按类型路由：
        text  → 走老路（切块入向量库）
        table → 走结构化（L02 的 markdown/HTML）
        image → 走 OCR（L03）或 VLM 描述（L04）
    bbox 全程携带——L06 的「页码+区域」引用溯源就靠它。

Element 是后面所有课的数据底座，type ∈ {text, table, image}。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

# 元素类型：文本 / 表格 / 图片。后面每课按这个 type 分类路由。
ElementType = Literal["text", "table", "image"]

# 表格检测的启发式阈值：一页上交叉的直线（横线+竖线）超过这个数，判定为表格页。
# 调参依据：毒文档表格页有 13 条线（6 横 + 7 竖），纯文本页通常 0-2 条（标题下划线）。
_TABLE_LINE_THRESHOLD = 6


@dataclass(frozen=True)
class Element:
    """版面元素：PDF 里的一个可分类单元，带类型和坐标。

    不可变（frozen=True）——和 IngestReport/Document 风格一致，构造新对象而非原地改。

    属性：
        type     —— text / table / image，下游路由依据
        content  —— text: 文本内容；table: 串行文本（L02 升级为结构化）；image: 图片描述或路径
        page     —— 页码（1-based，人读用），L06 引用溯源的「P3」就来自这里
        bbox     —— (x0, y0, x1, y1)，元素在页面上的矩形区域，L06 区域裁剪引用靠它
        source   —— 文件名，引用溯源展示用
    """

    type: ElementType
    content: str
    page: int
    bbox: tuple[float, float, float, float]
    source: str = ""

    def to_metadata(self) -> dict:
        """转成 Chroma metadata（ingest 时挂到 Document 上）。

        page / element_type 是 L06 引用溯源的关键字段；bbox 序列化成字符串
        （Chroma metadata 只支持 str/int/float/bool，不收 tuple）。
        """
        meta = {
            "page": self.page,
            "element_type": self.type,
            "bbox": ",".join(f"{v:.1f}" for v in self.bbox),
        }
        if self.source:
            meta["source"] = self.source
        return meta


@dataclass(frozen=True)
class ParseReport:
    """一次 parse_pdf 的统计报告（不可变）。"""

    source: str
    pages: int
    elements: tuple[Element, ...] = field(default_factory=tuple)
    text_count: int = 0
    table_count: int = 0
    image_count: int = 0

    def by_type(self) -> dict[str, int]:
        return {"text": self.text_count, "table": self.table_count, "image": self.image_count}


def _is_table_page(page: fitz.Page) -> bool:
    """启发式判定：页面是否有大量交叉直线（表格框线）。

    表格的本质是「网格」——横线和竖线相交。纯文本页顶多有一条标题下划线。
    数 get_drawings() 里的直线段，超过阈值就判定为表格页。
    这是 L02 的前置：先把「这页有表格」认出来，L02 再做结构化抽取。
    """
    drawings = page.get_drawings()
    line_count = 0
    for d in drawings:
        for item in d.get("items", []):
            # item 形如 ("l", p1, p2) 表示一条线段（l = line）
            if item and item[0] == "l":
                line_count += 1
    return line_count >= _TABLE_LINE_THRESHOLD


def parse_pdf(pdf_path: str | Path) -> list[Element]:
    """解析 PDF，返回带类型和坐标的元素流。

    每页按以下逻辑分类：
        1. 文本层字符量 ≈ 0 且有图片 → image 元素（扫描页）
        2. 大量交叉直线 → table 元素（表格页，content 暂存串行文本，L02 升级）
        3. 其余 → text 元素（正常文本块）

    注意：这是「分类路由」的第一步——认出元素类型，不做内容转换。
    扫描页此时还是 image、内容为空；表格还是串行文本。真正「翻译」在 L02-L04。
    """
    path = Path(pdf_path)
    doc = fitz.open(str(path))
    elements: list[Element] = []
    source = path.name

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1  # 1-based，人读用
        page_text = page.get_text().strip()
        char_count = len(page_text)
        has_images = len(page.get_images()) > 0
        is_table = _is_table_page(page)

        # ── 分类路由（L00 五层全景图的「解析层」核心逻辑）──
        if char_count == 0 and has_images:
            # 扫描页：文字渲染成图片，文本层为空 → image 元素
            # content 暂为空字符串，L03 的 OCR 会填上识别文本
            img_bbox = _full_page_bbox(page)
            elements.append(
                Element(
                    type="image",
                    content="",
                    page=page_num,
                    bbox=img_bbox,
                    source=source,
                )
            )
        elif is_table:
            # 表格页：有文本层但被拍平成串行 → table 元素
            # content 暂存串行文本，L02 会用 pdfplumber 升级成 markdown/HTML
            elements.append(
                Element(
                    type="table",
                    content=page_text,
                    page=page_num,
                    bbox=_full_page_bbox(page),
                    source=source,
                )
            )
        else:
            # 正常文本页：按 block 拆成多个 text 元素（保 bbox 精度）
            # 用 get_text("blocks") 拿到带坐标的文本块，比整页一坨更利于溯源
            blocks = page.get_text("blocks")
            meaningful = [
                b for b in blocks
                if len(b) >= 5 and b[4].strip()  # b[4] 是文本，过滤空块
            ]
            if meaningful:
                for b in meaningful:
                    # b = (x0, y0, x1, y1, text, block_no, block_type)
                    elements.append(
                        Element(
                            type="text",
                            content=b[4].strip(),
                            page=page_num,
                            bbox=(b[0], b[1], b[2], b[3]),
                            source=source,
                        )
                    )
            elif char_count > 0:
                # 有文本但拿不到 block（极端情况），退化为整页一个 text 元素
                elements.append(
                    Element(
                        type="text",
                        content=page_text,
                        page=page_num,
                        bbox=_full_page_bbox(page),
                        source=source,
                    )
                )
            # 图文混排页：文本 block 之外，把图片也单独列为 image 元素
            if has_images and char_count > 0:
                for img_info in page.get_image_info():
                    bbox = img_info.get("bbox")
                    if bbox:
                        elements.append(
                            Element(
                                type="image",
                                content="",
                                page=page_num,
                                bbox=tuple(bbox),
                                source=source,
                            )
                        )

    doc.close()
    return elements


def _full_page_bbox(page: fitz.Page) -> tuple[float, float, float, float]:
    """整页的 bbox（扫描页/表格页用整页区域作 bbox）。"""
    r = page.rect
    return (r.x0, r.y0, r.x1, r.y1)


def summarize(elements: list[Element]) -> ParseReport:
    """把元素流汇总成报告（逐页类型统计，code.py 演示用）。"""
    by_type: dict[str, int] = {"text": 0, "table": 0, "image": 0}
    pages = max((e.page for e in elements), default=0)
    source = elements[0].source if elements else ""
    for e in elements:
        by_type[e.type] = by_type.get(e.type, 0) + 1
    return ParseReport(
        source=source,
        pages=pages,
        elements=tuple(elements),
        text_count=by_type["text"],
        table_count=by_type["table"],
        image_count=by_type["image"],
    )
