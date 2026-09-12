from __future__ import annotations

import asyncio
import re
from io import BytesIO
from urllib.request import urlopen
from xml.sax.saxutils import escape as _xml_escape

from application.dtos.export_result import ExportResult
from application.ports.document_exporter_port import DocumentExporterPort
from domain.entities.document import Document
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import (
    APASectionType,
    normalize_document_styles,
)
from domain.value_objects.document_node import (
    BLOCK_QUOTE,
    BULLETED_LIST,
    FIELD,
    HEADING_1,
    HEADING_2,
    HEADING_3,
    HEADING_4,
    HEADING_5,
    HYPERLINK,
    IMAGE,
    NUMBERED_LIST,
    PAGE_BREAK,
    PARAGRAPH,
    SECTION_BREAK,
    TAB,
    TABLE,
    TABLE_OF_CONTENTS,
    DocumentNode,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

_PAGE_SIZES = {"letter": letter, "a4": A4}
_ALIGN_MAP = {
    "left": TA_LEFT,
    "center": TA_CENTER,
    "right": TA_RIGHT,
    "justify": TA_JUSTIFY,
}
_FONT_FAMILIES = {
    "times new roman": (
        "Times-Roman",
        "Times-Bold",
        "Times-Italic",
        "Times-BoldItalic",
    ),
    "times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "serif": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "arial": (
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Helvetica-BoldOblique",
    ),
    "helvetica": (
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Helvetica-BoldOblique",
    ),
    "sans-serif": (
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Helvetica-BoldOblique",
    ),
    "courier": (
        "Courier",
        "Courier-Bold",
        "Courier-Oblique",
        "Courier-BoldOblique",
    ),
    "monospace": (
        "Courier",
        "Courier-Bold",
        "Courier-Oblique",
        "Courier-BoldOblique",
    ),
}

_HIGHLIGHT_COLORS = {
    "yellow": "#FFFF00",
    "green": "#00FF00",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "blue": "#0000FF",
    "red": "#FF0000",
    "darkBlue": "#000080",
    "darkCyan": "#008080",
    "darkGreen": "#008000",
    "darkMagenta": "#800080",
    "darkRed": "#800000",
    "darkYellow": "#808000",
    "darkGray": "#808080",
    "lightGray": "#C0C0C0",
    "black": "#000000",
    "white": "#FFFFFF",
}


def _centered_style(style: ParagraphStyle) -> ParagraphStyle:
    """Force the APA cover-page alignment after applying editor styles."""
    return ParagraphStyle(style.name, parent=style, alignment=TA_CENTER)


class _ApaDocTemplate(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        style_name = getattr(flowable.style, "name", "")
        if style_name == "Heading1":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
        elif style_name == "Heading2":
            self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


class PdfDocumentExporterAdapter(DocumentExporterPort):
    async def export(self, document: Document) -> ExportResult:
        try:
            pdf_bytes = await asyncio.to_thread(self._build_sync, document)
        except Exception as exc:
            raise DocumentBuildError(f"PDF export failed: {exc}") from exc

        return ExportResult(
            url=None,
            file_bytes=pdf_bytes,
            file_name=f"{_safe_filename(document.title)}.pdf",
            content_type="application/pdf",
        )

    def _build_sync(self, document: Document) -> bytes:
        pdf_bytes, _ = self._build_with_toc_entries(document)
        return pdf_bytes

    def build_toc_entries(
        self, document: Document
    ) -> list[tuple[int, str, int]]:
        """Lay out a document and return its resolved TOC entries.

        ReportLab needs the same multi-pass build used by PDF export to know
        the final page for every heading. DOCX export uses this method to
        seed the Word TOC field with useful content on its first render.
        """
        _, entries = self._build_with_toc_entries(document)
        return entries

    def _build_with_toc_entries(
        self, document: Document
    ) -> tuple[bytes, list[tuple[int, str, int]]]:
        doc_styles = normalize_document_styles(document.global_style)
        page_size = _resolve_page_size(doc_styles)
        margins = _resolve_margins(doc_styles)
        content_width = page_size[0] - margins["left"] - margins["right"]
        styles = _build_styles(doc_styles)

        buffer = BytesIO()
        doc = _ApaDocTemplate(
            buffer,
            pagesize=page_size,
            leftMargin=margins["left"],
            rightMargin=margins["right"],
            topMargin=margins["top"],
            bottomMargin=margins["bottom"],
            title=document.title,
        )
        frame = Frame(
            margins["left"],
            margins["bottom"],
            content_width,
            page_size[1] - margins["top"] - margins["bottom"],
            id="normal",
        )
        on_page = _make_on_page(
            page_size=page_size,
            margins=margins,
            background=_parse_color(
                doc_styles.get("backgroundColor"), default=None
            ),
            show_page_numbers=doc_styles["showPageNumbers"],
            page_number_position=doc_styles["pageNumberPosition"],
        )
        doc.addPageTemplates(
            [PageTemplate(id="all", frames=[frame], onPage=on_page)]
        )

        story: list = []
        story += self._build_cover_page(document, styles, content_width)
        story += self._build_toc_page(document, styles, content_width)

        for section_type in (
            APASectionType.INTRODUCTION,
            APASectionType.BODY,
            APASectionType.CONCLUSION,
        ):
            story += self._build_section(
                document, section_type, styles, content_width
            )

        story += self._build_references(document, styles, content_width)

        # multiBuild (not build): see _ApaDocTemplate docstring — this is
        # what lets the index show real, adapter-discovered page numbers.
        doc.multiBuild(story)
        toc = next(
            (
                flowable
                for flowable in story
                if isinstance(flowable, TableOfContents)
            ),
            None,
        )
        raw_entries = getattr(toc, "_lastEntries", ()) if toc else ()
        entries = [
            (int(level), str(text), int(page_number))
            for level, text, page_number, _ in raw_entries
        ]
        return buffer.getvalue(), entries

    def _build_cover_page(
        self, document: Document, styles: dict, content_width: float
    ) -> list:

        section = document.get_section(APASectionType.PRESENTATION)

        elements: list = [
            Spacer(1, 2.5 * inch),
            Paragraph(
                _render_inline(
                    section.heading.children, section.heading.styles
                )
                if section is not None
                else _xml_escape(document.title),
                _centered_style(
                    _apply_block_style(
                        styles["TitleCover"],
                        section.heading.styles if section is not None else {},
                    )
                ),
            ),
            Spacer(1, 0.5 * inch),
        ]
        if section is None:
            return elements

        for node in section.body_nodes:
            if node.type == PAGE_BREAK:
                elements += _render_block(node, styles, content_width)
                continue
            elements.append(
                Paragraph(
                    _render_inline(node.children, node.styles),
                    _centered_style(
                        _apply_block_style(styles["CoverLine"], node.styles)
                    ),
                )
            )
        return elements

    def _build_toc_page(
        self, document: Document, styles: dict, content_width: float
    ) -> list:
        index_section = document.get_section(APASectionType.INDEX)
        index_title = index_section.title if index_section else "Índice"

        # "Heading1Plain" is intentionally NOT the "Heading1" style, so this
        # heading doesn't register itself as a TOC entry.
        elements: list = [
            Paragraph(
                _render_inline(
                    index_section.heading.children,
                    index_section.heading.styles,
                )
                if index_section is not None
                else _xml_escape(index_title),
                _paragraph_style(
                    styles["Heading1Plain"],
                    index_section.heading.styles,
                    index_section.heading.children,
                )
                if index_section is not None
                else styles["Heading1Plain"],
            )
        ]

        if index_section is None:
            # Defensive fallback for a document somehow missing its index
            # section entirely (should not happen — build_index_section
            # always runs) — still produce a working TOC page.
            elements.append(self._make_toc_flowable(styles))
            elements.append(PageBreak())
            return elements

        for node in index_section.body_nodes:
            if node.type == TABLE_OF_CONTENTS:
                elements.append(self._make_toc_flowable(styles))
            elif node.type == PAGE_BREAK:
                elements += _render_block(node, styles, content_width)
            else:
                elements += _render_block(node, styles, content_width)
        return elements

    def _make_toc_flowable(self, styles: dict) -> TableOfContents:
        # The node's own `entries` (see table_of_contents_builder.py) are
        # only an editor-side preview — ReportLab computes the real,
        # paginated entries itself from the Heading1/Heading2 paragraphs
        # rendered elsewhere in the story (see _ApaDocTemplate.afterFlowable).
        toc = TableOfContents()
        toc.levelStyles = [styles["TOCLevel0"], styles["TOCLevel1"]]
        toc.dotsMinLevel = (
            0  # dot leaders on every level, not just sub-entries
        )
        return toc

    def _build_section(
        self,
        document: Document,
        section_type: APASectionType,
        styles: dict,
        content_width: float,
    ) -> list:
        section = document.get_section(section_type)
        if section is None:
            return []

        elements: list = []
        if section_type is not APASectionType.BODY:
            elements.append(
                Paragraph(
                    _render_inline(
                        section.heading.children, section.heading.styles
                    ),
                    _paragraph_style(
                        styles["Heading1"],
                        section.heading.styles,
                        section.heading.children,
                    ),
                )
            )
        for node in section.body_nodes:
            elements += _render_block(node, styles, content_width)
        return elements

    def _build_references(
        self, document: Document, styles: dict, content_width: float
    ) -> list:
        sources_section = document.get_section(APASectionType.SOURCES)
        title = sources_section.title if sources_section else "References"
        elements: list = [
            Paragraph(
                _render_inline(
                    sources_section.heading.children,
                    sources_section.heading.styles,
                )
                if sources_section is not None
                else _xml_escape(title),
                _paragraph_style(
                    styles["Heading1"],
                    sources_section.heading.styles,
                    sources_section.heading.children,
                )
                if sources_section is not None
                else styles["Heading1"],
            )
        ]
        imported_references = sources_section is not None and any(
            node.metadata.get("docxImported")
            for node in sources_section.body_nodes
        )
        if sources_section is not None and imported_references:
            for node in sources_section.body_nodes:
                if node.type != PAGE_BREAK:
                    elements += _render_block(node, styles, content_width)
            return elements
        for ref in sorted(
            document.sources, key=lambda r: (r.author or "").lower()
        ):
            elements.append(
                Paragraph(
                    _xml_escape(ref.to_apa_string()), styles["Reference"]
                )
            )
        if not document.sources:
            elements.append(
                Paragraph("No sources were provided.", styles["Body"])
            )
        return elements


def _build_styles(doc_styles: dict) -> dict[str, ParagraphStyle]:
    regular, bold, italic, bold_italic = _resolve_font_family(
        doc_styles.get("fontFamily")
    )
    base_size = _parse_length(doc_styles.get("fontSize"), default=12) or 12
    line_height = _coerce_float(doc_styles.get("lineHeight"), default=2.0)
    leading = base_size * line_height
    text_color = _parse_color(doc_styles.get("color"), default=colors.black)

    return {
        "TitleCover": ParagraphStyle(
            "TitleCover",
            fontName=bold,
            fontSize=base_size,
            leading=leading,
            alignment=TA_CENTER,
            textColor=text_color,
        ),
        "CoverLine": ParagraphStyle(
            "CoverLine",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            alignment=TA_CENTER,
            textColor=text_color,
        ),
        "Heading1": ParagraphStyle(
            "Heading1",
            fontName=bold,
            fontSize=base_size,
            leading=leading,
            alignment=TA_CENTER,
            spaceBefore=12,
            spaceAfter=12,
            textColor=text_color,
        ),
        "Heading1Plain": ParagraphStyle(
            "Heading1Plain",
            fontName=bold,
            fontSize=base_size,
            leading=leading,
            alignment=TA_CENTER,
            spaceBefore=12,
            spaceAfter=12,
            textColor=text_color,
        ),
        # APA 7 level-2 heading: flush left, bold, own line.
        "Heading2": ParagraphStyle(
            "Heading2",
            fontName=bold,
            fontSize=base_size,
            leading=leading,
            alignment=TA_LEFT,
            spaceBefore=12,
            spaceAfter=6,
            textColor=text_color,
        ),
        # Level 3: flush left, bold italic. Levels 4-5 approximated the
        # same way (see module-level limitations note) rather than as true
        # run-in headings.
        "Heading3": ParagraphStyle(
            "Heading3",
            fontName=bold_italic,
            fontSize=base_size,
            leading=leading,
            alignment=TA_LEFT,
            spaceBefore=10,
            spaceAfter=6,
            textColor=text_color,
        ),
        "Heading4": ParagraphStyle(
            "Heading4",
            fontName=bold,
            fontSize=base_size,
            leading=leading,
            alignment=TA_LEFT,
            leftIndent=0.5 * inch,
            spaceBefore=8,
            spaceAfter=4,
            textColor=text_color,
        ),
        "Heading5": ParagraphStyle(
            "Heading5",
            fontName=bold_italic,
            fontSize=base_size,
            leading=leading,
            alignment=TA_LEFT,
            leftIndent=0.5 * inch,
            spaceBefore=8,
            spaceAfter=4,
            textColor=text_color,
        ),
        "Body": ParagraphStyle(
            "Body",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            alignment=TA_JUSTIFY,
            firstLineIndent=0.5 * inch,
            textColor=text_color,
        ),
        "BlockQuote": ParagraphStyle(
            "BlockQuote",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            alignment=TA_JUSTIFY,
            leftIndent=0.5 * inch,
            rightIndent=0.5 * inch,
            spaceBefore=6,
            spaceAfter=6,
            textColor=text_color,
        ),
        "Bullet": ParagraphStyle(
            "Bullet",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            alignment=TA_JUSTIFY,
            leftIndent=0.75 * inch,
            firstLineIndent=-0.25 * inch,
            spaceAfter=4,
            textColor=text_color,
        ),
        "Numbered": ParagraphStyle(
            "Numbered",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            alignment=TA_JUSTIFY,
            leftIndent=0.75 * inch,
            firstLineIndent=-0.25 * inch,
            spaceAfter=4,
            textColor=text_color,
        ),
        "Reference": ParagraphStyle(
            "Reference",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            alignment=TA_LEFT,
            leftIndent=0.5 * inch,
            firstLineIndent=-0.5 * inch,
            spaceAfter=12,
            textColor=text_color,
        ),
        "Caption": ParagraphStyle(
            "Caption",
            fontName=italic,
            fontSize=max(base_size - 2, 8),
            leading=leading * 0.8,
            alignment=TA_CENTER,
            spaceBefore=4,
            spaceAfter=12,
            textColor=text_color,
        ),
        "TOCLevel0": ParagraphStyle(
            "TOCLevel0",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            leftIndent=0,
            firstLineIndent=0,
            spaceAfter=4,
        ),
        "TOCLevel1": ParagraphStyle(
            "TOCLevel1",
            fontName=regular,
            fontSize=base_size,
            leading=leading,
            leftIndent=0.3 * inch,
            firstLineIndent=0,
            spaceAfter=4,
        ),
    }


def _make_on_page(
    *,
    page_size,
    margins: dict[str, float],
    background,
    show_page_numbers: bool = True,
    page_number_position: str = "top-right",
):
    def _on_page(canvas, doc) -> None:
        canvas.saveState()
        if background is not None:
            canvas.setFillColor(background)
            canvas.rect(0, 0, page_size[0], page_size[1], fill=1, stroke=0)
        if show_page_numbers:
            _draw_page_number(
                canvas,
                page_size=page_size,
                margins=margins,
                position=page_number_position,
            )
        canvas.restoreState()

    return _on_page


def _draw_page_number(
    canvas, *, page_size, margins: dict[str, float], position: str
) -> None:
    canvas.setFont("Times-Roman", 12)
    canvas.setFillColor(colors.black)
    page_num = str(canvas.getPageNumber())

    if position == "bottom-center":
        canvas.drawCentredString(page_size[0] / 2, 0.5 * inch, page_num)
    elif position == "bottom-right":
        canvas.drawRightString(
            page_size[0] - margins["right"], 0.5 * inch, page_num
        )
    else:  # "top-right" (default)
        canvas.drawRightString(
            page_size[0] - margins["right"],
            page_size[1] - 0.75 * inch,
            page_num,
        )


# --- inline rendering (marks) ------------------------------------------------

_MARK_TAG_ORDER = (
    "bold",
    "italic",
    "underline",
    "strikethrough",
    "script",
    "font",
    "link",
)


def _render_inline(
    nodes: tuple[DocumentNode, ...], inherited_styles: dict | None = None
) -> str:
    """Render inline v2 nodes into ReportLab mini-markup."""
    rendered: list[str] = []
    for node in nodes:
        if node.type == HYPERLINK:
            url = _xml_escape(str(node.metadata.get("url", "")))
            children = _render_inline(node.children, inherited_styles)
            rendered.append(f'<link href="{url}">{children}</link>')
        elif node.type == TAB:
            rendered.append("&#9;")
        elif node.type == FIELD:
            rendered.append("")
        else:
            rendered.append(_render_leaf(node, inherited_styles))
    return "".join(rendered)


def _render_leaf(
    node: DocumentNode, inherited_styles: dict | None = None
) -> str:
    if node.text is None:
        raise DocumentBuildError(
            f"Expected a leaf text node, got block '{node.type}'."
        )
    chunk = _xml_escape(node.text)

    by_type = {
        **(inherited_styles or {}),
        **{
            mark.type: True if mark.value is None else mark.value
            for mark in node.marks
        },
    }

    if "code" in by_type:
        chunk = f'<font face="Courier">{chunk}</font>'
    font_attrs = ""
    if "color" in by_type:
        font_attrs += f' color="{_xml_escape(str(by_type["color"]))}"'
    if "fontSize" in by_type:
        size_pt = _parse_length(by_type["fontSize"], default=None)
        if size_pt:
            font_attrs += f' size="{size_pt:g}"'
    if "fontFamily" in by_type:
        regular, *_ = _resolve_font_family(str(by_type["fontFamily"]))
        font_attrs += f' face="{regular}"'
    background = by_type.get("backgroundShading")
    if background is None:
        highlight = by_type.get("highlight")
        if highlight != "none":
            background = _HIGHLIGHT_COLORS.get(str(highlight), highlight)
    if _parse_color(background, default=None) is not None:
        font_attrs += f' backColor="{_xml_escape(str(background))}"'
    if font_attrs:
        chunk = f"<font{font_attrs}>{chunk}</font>"

    if "script" in by_type:
        tag = "super" if by_type["script"] == "superscript" else "sub"
        chunk = f"<{tag}>{chunk}</{tag}>"
    if "strikethrough" in by_type:
        chunk = f"<strike>{chunk}</strike>"
    if "underline" in by_type:
        chunk = f"<u>{chunk}</u>"
    if "italic" in by_type:
        chunk = f"<i>{chunk}</i>"
    if "bold" in by_type:
        chunk = f"<b>{chunk}</b>"
    if "link" in by_type:
        url = _xml_escape(str(by_type["link"].get("url", "")))
        chunk = f'<link href="{url}">{chunk}</link>'
    return chunk


# --- block rendering ----------------------------------------------------

_HEADING_STYLE_NAMES = {
    HEADING_1: "Heading1",
    HEADING_2: "Heading2",
    HEADING_3: "Heading3",
    HEADING_4: "Heading4",
    HEADING_5: "Heading5",
}


def _render_block(
    node: DocumentNode,
    styles: dict,
    content_width: float,
    inherited_styles: dict | None = None,
) -> list:
    resolved_styles = {**(inherited_styles or {}), **node.styles}
    if node.type in {PAGE_BREAK, SECTION_BREAK}:
        return [PageBreak()]

    if node.type in _HEADING_STYLE_NAMES:
        base = styles[_HEADING_STYLE_NAMES[node.type]]
        style = _paragraph_style(base, resolved_styles, node.children)
        return [
            Paragraph(_render_inline(node.children, resolved_styles), style)
        ]

    if node.type == PARAGRAPH:
        style = _paragraph_style(
            styles["Body"], resolved_styles, node.children
        )
        paragraph = Paragraph(
            _render_inline(node.children, resolved_styles), style
        )
        return _wrap_with_box(paragraph, resolved_styles, content_width)

    if node.type == BLOCK_QUOTE:
        style = _paragraph_style(
            styles["BlockQuote"], resolved_styles, node.children
        )
        paragraph = Paragraph(
            _render_inline(node.children, resolved_styles), style
        )
        return _wrap_with_box(paragraph, resolved_styles, content_width)

    if node.type == BULLETED_LIST:
        return [
            Paragraph(
                f"•  {_render_inline(item.children, item_styles)}",
                _paragraph_style(styles["Bullet"], item_styles, item.children),
            )
            for item in node.children
            for item_styles in ({**resolved_styles, **item.styles},)
        ]

    if node.type == NUMBERED_LIST:
        return [
            Paragraph(
                f"{i}.  {_render_inline(item.children, item_styles)}",
                _paragraph_style(
                    styles["Numbered"], item_styles, item.children
                ),
            )
            for i, item in enumerate(node.children, start=1)
            for item_styles in ({**resolved_styles, **item.styles},)
        ]

    if node.type == IMAGE:
        return _render_image(node, styles, content_width)

    if node.type == TABLE:
        return [
            _render_table(node, styles, content_width, inherited_styles or {})
        ]

    raise DocumentBuildError(
        f"Unsupported block node in section: '{node.type}'"
    )


def _render_table(
    node: DocumentNode,
    styles: dict,
    content_width: float,
    inherited_styles: dict,
) -> Table:
    rows = node.children  # each is a TABLE_ROW node
    table_styles = {**inherited_styles, **node.styles}
    if not rows:
        raise DocumentBuildError("A 'table' node has no rows.")

    n_cols = len(rows[0].children)
    requested_widths = [cell.styles.get("width") for cell in rows[0].children]
    column_widths = [
        _resolve_dimension(value, content_width, default=None)
        for value in requested_widths
    ]
    if any(width is None for width in column_widths):
        col_width = content_width / n_cols if n_cols else content_width
        column_widths = [col_width] * n_cols

    data: list[list] = []
    for row in rows:
        if len(row.children) != n_cols:
            raise DocumentBuildError(
                "Every 'table-row' must have the same number of "
                f"'table-cell' children (expected {n_cols}, got "
                f"{len(row.children)})."
            )
        row_cells = []
        row_styles = {**table_styles, **row.styles}
        for cell_index, cell in enumerate(row.children):
            cell_styles = {**row_styles, **cell.styles}
            cell_flowables: list = []
            for child in cell.children:
                child_styles = cell_styles
                if "textIndent" not in child.styles:
                    child_styles = {**cell_styles, "textIndent": 0}
                cell_flowables += _render_block(
                    child,
                    styles,
                    column_widths[cell_index],
                    child_styles,
                )
            row_cells.append(cell_flowables)
        data.append(row_cells)

    row_heights = [
        _parse_length(row.styles.get("height"), default=None) for row in rows
    ]
    table = Table(data, colWidths=column_widths, rowHeights=row_heights)
    alignment = str(
        node.styles.get("textAlign", node.styles.get("alignment", "center"))
    ).upper()
    table.hAlign = (
        alignment if alignment in {"LEFT", "CENTER", "RIGHT"} else "CENTER"
    )
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if len(data) > 1:
        # First row is conventionally the header row.
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke))
    table_background = _parse_color(
        node.styles.get("backgroundColor"), default=None
    )
    if table_background is not None:
        commands.append(("BACKGROUND", (0, 0), (-1, -1), table_background))
    for row_index, row in enumerate(rows):
        for cell_index, cell in enumerate(row.children):
            background = _parse_color(
                cell.styles.get("backgroundColor"), default=None
            )
            if background is not None:
                commands.append(
                    (
                        "BACKGROUND",
                        (cell_index, row_index),
                        (cell_index, row_index),
                        background,
                    )
                )
    table.setStyle(TableStyle(commands))
    return table


def _paragraph_style(
    base: ParagraphStyle,
    node_styles: dict,
    nodes: tuple[DocumentNode, ...],
) -> ParagraphStyle:
    style = _apply_block_style(base, node_styles)
    largest_size = _largest_font_size(nodes, style.fontSize)
    space_after = style.spaceAfter
    if largest_size * 1.2 > style.leading:
        # ReportLab's per-line auto-leading measures the tall line correctly,
        # but undercounts the flowable's bottom edge by one regular line when
        # a much larger inline run is present. Reserve that line so the next
        # paragraph cannot be drawn over the final line of this one.
        space_after += style.leading
    return ParagraphStyle(
        style.name,
        parent=style,
        autoLeading="max",
        leading=style.leading,
        spaceAfter=space_after,
    )


def _largest_font_size(
    nodes: tuple[DocumentNode, ...], default: float
) -> float:
    largest = default
    for node in nodes:
        if node.text is None:
            largest = max(largest, _largest_font_size(node.children, default))
            continue
        mark = next(
            (mark for mark in node.marks if mark.type == "fontSize"), None
        )
        if mark is not None:
            largest = max(
                largest,
                _parse_length(mark.value, default=default) or default,
            )
    return largest


def _apply_block_style(
    base: ParagraphStyle, node_styles: dict
) -> ParagraphStyle:
    if not node_styles:
        return base

    overrides: dict = {}
    effective_size = base.fontSize
    if "fontSize" in node_styles:
        value = _parse_length(node_styles["fontSize"], default=None)
        if value is not None:
            effective_size = value
            overrides["fontSize"] = value
    if "fontFamily" in node_styles:
        regular, bold, italic, bold_italic = _resolve_font_family(
            str(node_styles["fontFamily"])
        )
        if node_styles.get("bold") and node_styles.get("italic"):
            overrides["fontName"] = bold_italic
        elif node_styles.get("bold"):
            overrides["fontName"] = bold
        elif node_styles.get("italic"):
            overrides["fontName"] = italic
        else:
            overrides["fontName"] = regular
    if "color" in node_styles:
        color = _parse_color(node_styles["color"], default=None)
        if color is not None:
            overrides["textColor"] = color
    if "textAlign" in node_styles:
        align = _ALIGN_MAP.get(str(node_styles["textAlign"]).lower())
        if align is not None:
            overrides["alignment"] = align
    if "textIndent" in node_styles:
        value = _parse_length(node_styles["textIndent"], default=None)
        if value is not None:
            overrides["firstLineIndent"] = value
    if "spaceBefore" in node_styles:
        value = _parse_length(node_styles["spaceBefore"], default=None)
        if value is not None:
            overrides["spaceBefore"] = value
    if "marginBottom" in node_styles:
        value = _parse_length(node_styles["marginBottom"], default=None)
        if value is not None:
            overrides["spaceAfter"] = value
    if "marginLeft" in node_styles:
        value = _parse_length(node_styles["marginLeft"], default=None)
        if value is not None:
            overrides["leftIndent"] = value
    if "marginRight" in node_styles:
        value = _parse_length(node_styles["marginRight"], default=None)
        if value is not None:
            overrides["rightIndent"] = value
    if "lineHeight" in node_styles:
        leading = _resolve_line_height(
            node_styles["lineHeight"], font_size=effective_size
        )
        if leading is not None:
            overrides["leading"] = leading
    elif effective_size != base.fontSize:
        overrides["leading"] = effective_size * (base.leading / base.fontSize)

    if not overrides:
        return base
    # IMPORTANT: keep the SAME style name as `base` (not a renamed
    # "-override-" variant). These ParagraphStyle objects are never
    # registered in a shared StyleSheet1, so name reuse is harmless — but
    # _ApaDocTemplate.afterFlowable matches TOC entries by exact style
    # name ("Heading1"/"Heading2"). Every heading the AI writes always
    # carries a 'styles' override (textAlign is mandatory), so renaming
    # the style here silently dropped EVERY heading-2 from the table of
    # contents while heading-1 section titles (rendered separately,
    # without going through this function) kept working — that's the bug
    # this comment is guarding against regressing.
    return ParagraphStyle(base.name, parent=base, **overrides)


def _wrap_with_box(
    paragraph: Paragraph, node_styles: dict, content_width: float
) -> list:
    """Best-effort approximation of block background/border via a
    single-cell Table — ReportLab paragraphs have no native background."""
    bg = node_styles.get("backgroundColor")
    border_left = node_styles.get("borderLeft")
    if not bg and not border_left:
        return [paragraph]

    commands = [
        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            _parse_length(node_styles.get("paddingLeft"), default=6),
        ),
        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            _parse_length(node_styles.get("paddingRight"), default=6),
        ),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if bg:
        color = _parse_color(bg, default=None)
        if color is not None:
            commands.append(("BACKGROUND", (0, 0), (-1, -1), color))
    if border_left:
        width_pt, color = _parse_border(border_left)
        if color is not None:
            commands.append(("LINEBEFORE", (0, 0), (-1, -1), width_pt, color))

    table = Table([[paragraph]], colWidths=[content_width])
    table.setStyle(TableStyle(commands))
    return [table]


def _render_image(
    node: DocumentNode, styles: dict, content_width: float
) -> list:
    try:
        image_bytes = _fetch_image_bytes(node.src)
        reader = ImageReader(BytesIO(image_bytes))
        natural_w, natural_h = reader.getSize()
    except Exception:
        placeholder = node.alt or node.caption or node.src or "image"
        return [
            Paragraph(
                f"[Image unavailable: {_xml_escape(placeholder)}]",
                styles["Caption"],
            )
        ]

    width = _resolve_dimension(
        node.styles.get("width"), content_width, default=content_width
    )
    height = width * (natural_h / natural_w) if natural_w else None

    align = str(node.styles.get("alignment", "center")).upper()
    h_align = align if align in ("LEFT", "CENTER", "RIGHT") else "CENTER"

    elements: list = [
        Image(BytesIO(image_bytes), width=width, height=height, hAlign=h_align)
    ]
    if node.caption:
        elements.append(
            Paragraph(_xml_escape(node.caption), styles["Caption"])
        )
    return elements


def _fetch_image_bytes(src: str | None) -> bytes:
    if not src:
        raise DocumentBuildError("Image node has no 'src'.")
    with urlopen(src, timeout=10) as response:  # noqa: S310 - trusted, app-inserted URLs
        return response.read()


# --- small parsing helpers ------------------------------------------------


def _resolve_page_size(doc_styles: dict) -> tuple[float, float]:
    raw = doc_styles.get("pageSize", "letter")
    if isinstance(raw, dict):
        width = _parse_length(raw.get("width"), default=letter[0]) or letter[0]
        height = (
            _parse_length(raw.get("height"), default=letter[1]) or letter[1]
        )
    else:
        width, height = _PAGE_SIZES.get(str(raw).lower(), letter)

    landscape = (
        str(doc_styles.get("orientation", "portrait")).lower() == "landscape"
    )
    narrow, wide = min(width, height), max(width, height)
    return (wide, narrow) if landscape else (narrow, wide)


def _resolve_margins(doc_styles: dict) -> dict[str, float]:
    raw = doc_styles.get("pageMargin", "1in")
    default = _parse_length("1in", default=inch) or inch
    if isinstance(raw, dict):
        return {
            side: _parse_length(raw.get(side), default=default) or default
            for side in ("top", "bottom", "left", "right")
        }
    value = _parse_length(raw, default=default) or default
    return {"top": value, "bottom": value, "left": value, "right": value}


def _resolve_font_family(name: str | None) -> tuple[str, str, str, str]:
    if not name:
        return _FONT_FAMILIES["times new roman"]
    key = name.split(",")[0].strip().strip('"').lower()
    return _FONT_FAMILIES.get(key, _FONT_FAMILIES["times new roman"])


def _resolve_dimension(
    value, content_width: float, *, default: float
) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if text.endswith("%"):
        try:
            pct = float(text[:-1]) / 100.0
        except ValueError:
            return default
        return content_width * pct
    return _parse_length(text, default=default) or default


def _parse_length(value, *, default):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    try:
        if text.endswith("in"):
            return float(text[:-2]) * inch
        if text.endswith("pt"):
            return float(text[:-2])
        if text.endswith("px"):
            return float(text[:-2]) * 0.75  # 96dpi assumption
        if text.endswith("cm"):
            return float(text[:-2]) * 28.3465
        if text.endswith("mm"):
            return float(text[:-2]) * 2.83465
        return float(text)
    except ValueError:
        return default


def _parse_color(value, *, default):
    if not value:
        return default
    try:
        return colors.HexColor(str(value))
    except Exception:
        return default


def _parse_border(value: str) -> tuple[float, colors.Color | None]:
    width_pt = 1.0
    color = None
    for part in str(value).split():
        if re.match(r"^[\d.]+(px|pt|in)$", part):
            width_pt = _parse_length(part, default=width_pt) or width_pt
        elif part.startswith("#") or part.isalpha():
            parsed = _parse_color(part, default=None)
            if parsed is not None:
                color = parsed
    return width_pt, color


def _coerce_float(value, *, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_line_height(value, *, font_size: float) -> float | None:
    """Resolve a unitless multiplier or an absolute CSS-like length."""
    if isinstance(value, (int, float)):
        return font_size * float(value)
    text = str(value).strip().lower()
    if text.endswith(("pt", "px", "in", "cm", "mm")):
        return _parse_length(text, default=None)
    factor = _coerce_float(text, default=None)
    return font_size * factor if factor is not None else None


def _safe_filename(title: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]", "", title).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or "document"
