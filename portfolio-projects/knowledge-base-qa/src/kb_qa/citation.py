"""引用溯源：把引用升级到「文档+页码+区域(bbox)」（doc-intelligence L06）。

可信度三部曲的第三步：
    frontier 让数字【可复算】（代码解释器）
    gui 让来源【可回访】（浏览器证据链）
    本课让引用【可回溯】（页码+区域截图）

为什么多模态下旧引用不够：
    表格数字、图表读数、OCR 文本都是【转换的产物】，转换就可能错。
    用户必须能一键回到原始位置核对，否则可信度崩塌。

实现路径：Element 的 page/bbox 全程携带 → generate 引用格式带页码 →
        可选返回区域裁剪图（PyMuPDF page.get_pixmap(clip=bbox)）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass(frozen=True)
class Citation:
    """一条引用（可回溯到原文档位置）。

    level 表示引用的精细度：
        text  —— 纯文字引用（source · section），最轻
        page  —— 页码引用（source · P3·表格），中等（默认）
        region —— 区域截图引用（+ 裁剪图文件路径），最可信
    """

    source: str
    page: int | None = None
    element_type: str = "text"
    bbox: tuple[float, float, float, float] | None = None
    clip_image_path: str | None = None  # 区域裁剪图（region 级才有）

    @property
    def level(self) -> str:
        if self.clip_image_path:
            return "region"
        if self.page:
            return "page"
        return "text"

    def display(self) -> str:
        """人读的引用字符串（给前端/日志展示）。"""
        type_cn = {"text": "文本", "table": "表格", "image": "图片"}.get(self.element_type, self.element_type)
        if self.page:
            return f"{self.source} · P{self.page}·{type_cn}"
        return self.source


def clip_region(
    pdf_path: str | Path,
    page: int,
    bbox: tuple[float, float, float, float],
    out_dir: str | Path | None = None,
    dpi: int = 150,
) -> Path:
    """裁剪 PDF 指定页的指定区域为 PNG（区域截图引用）。

    page 是 1-based（人读用），bbox 是 (x0, y0, x1, y1) 页面坐标。
    返回裁剪图文件路径。这是「最可信」的引用——用户直接看原图区域核对。
    """
    path = Path(pdf_path)
    doc = fitz.open(str(path))
    try:
        page_obj = doc[page - 1]  # 转 0-based
        clip = fitz.Rect(*bbox)
        pix = page_obj.get_pixmap(dpi=dpi, clip=clip)
    finally:
        doc.close()

    # 输出路径：默认放 data/multimodal_docs/clips/，文件名含页码+bbox
    if out_dir is None:
        out_dir = path.parent / "clips"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bbox_str = f"{int(bbox[0])}_{int(bbox[1])}_{int(bbox[2])}_{int(bbox[3])}"
    out_file = out_dir / f"{path.stem}_P{page}_{bbox_str}.png"
    pix.save(str(out_file))
    return out_file


def build_citation(
    source: str,
    page: int | None = None,
    element_type: str = "text",
    bbox: tuple[float, float, float, float] | None = None,
    pdf_path: str | Path | None = None,
    enable_clip: bool = False,
) -> Citation:
    """从检索结果的 metadata 构造 Citation。

    enable_clip=True 且提供 pdf_path + bbox 时，生成区域裁剪图（region 级）。
    默认 page 级（不裁剪，轻量）。
    """
    clip_path = None
    if enable_clip and pdf_path and page and bbox:
        try:
            clip_path = str(clip_region(pdf_path, page, bbox))
        except Exception:
            clip_path = None  # 裁剪失败不崩，降级为 page 级
    return Citation(
        source=source,
        page=page,
        element_type=element_type,
        bbox=bbox,
        clip_image_path=clip_path,
    )
