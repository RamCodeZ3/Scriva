from __future__ import annotations

import asyncio
from dataclasses import replace
from io import BytesIO

from application.ports.document_parser_port import DocumentParserPort
from docx import Document as DocxDocument
from docx.enum.text import WD_COLOR_INDEX
from docx.text.hyperlink import Hyperlink
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    BULLETED_LIST,
    HEADING_1,
    HEADING_2,
    HEADING_3,
    LIST_ITEM,
    MARK_BACKGROUND_SHADING,
    MARK_COLOR,
    MARK_FONT_FAMILY,
    MARK_FONT_SIZE,
    MARK_HIGHLIGHT,
    MARK_SCRIPT,
    MARK_STRIKETHROUGH,
    NUMBERED_LIST,
    PAGE_BREAK,
    PARAGRAPH,
    TABLE,
    TABLE_CELL,
    TABLE_OF_CONTENTS,
    TABLE_ROW,
    DocumentNode,
    Mark,
    hyperlink_node,
)

_SECTION_ATTR = "{urn:scriva:document}section-type"
_HIGHLIGHT_COLORS = {
    WD_COLOR_INDEX.YELLOW: "yellow",
    WD_COLOR_INDEX.BRIGHT_GREEN: "green",
    WD_COLOR_INDEX.TURQUOISE: "cyan",
    WD_COLOR_INDEX.PINK: "magenta",
    WD_COLOR_INDEX.RED: "red",
    WD_COLOR_INDEX.BLUE: "blue",
    WD_COLOR_INDEX.GRAY_25: "lightGray",
}


class DocxDocumentParserAdapter(DocumentParserPort):
    async def parse(self, content: bytes) -> list[APASection]:
        if not content:
            raise DocumentBuildError("The uploaded DOCX file is empty.")
        try:
            return await asyncio.to_thread(self._parse_sync, content)
        except DocumentBuildError:
            raise
        except Exception as exc:
            raise DocumentBuildError(f"DOCX parsing failed: {exc}") from exc

    def _parse_sync(self, content: bytes) -> list[APASection]:
        docx = DocxDocument(BytesIO(content))
        blocks = list(_iter_blocks(docx))
        sections: list[APASection] = []
        current_type: APASectionType | None = None
        heading: DocumentNode | None = None
        body: list[DocumentNode] = []
        inside_toc = False

        def flush() -> None:
            nonlocal body
            if heading is not None and current_type is not None:
                if not body:
                    body = [_paragraph("")]
                sections.append(APASection(current_type, heading, tuple(body)))

        for kind, item in blocks:
            marked_type = _marked_section_type(item)
            if marked_type is not None and marked_type != current_type:
                flush()
                current_type = marked_type
                heading_text = (
                    "Desarrollo"
                    if marked_type is APASectionType.BODY
                    else (
                        item.text.strip()
                        if kind == "paragraph" and item.text.strip()
                        else marked_type.value.replace("_", " ").title()
                    )
                )
                heading = (
                    _heading_node(item, marked_type)
                    if kind == "paragraph"
                    and marked_type is not APASectionType.BODY
                    else _block(
                        HEADING_1,
                        heading_text,
                        section_type=marked_type.value,
                    )
                )
                body = []
                # A BODY marker is attached to its first real content block.
                if marked_type is not APASectionType.BODY:
                    continue
            if kind == "table":
                if heading is not None:
                    node = _table_node(item)
                    body.append(_imported_node(node, current_type))
                continue
            paragraph = item
            text = paragraph.text.strip()
            if _contains_toc_start(paragraph):
                if heading is not None:
                    body.append(
                        DocumentNode(
                            type=TABLE_OF_CONTENTS,
                            styles=_paragraph_styles(paragraph),
                        )
                    )
                inside_toc = not _contains_field_end(paragraph)
                continue
            if inside_toc:
                if _contains_field_end(paragraph):
                    inside_toc = False
                continue
            leading_page_breaks = _page_break_before_count(paragraph)
            inline_page_breaks = _inline_page_break_count(paragraph)
            if not text and (leading_page_breaks or inline_page_breaks):
                if heading is not None:
                    body.extend(
                        DocumentNode(type=PAGE_BREAK)
                        for _ in range(
                            leading_page_breaks + inline_page_breaks
                        )
                    )
                continue
            if not text:
                if heading is not None:
                    body.append(_paragraph(" "))
                continue
            style = paragraph.style.name if paragraph.style else ""
            detected = _section_type(text, style, current_type)
            if detected is not None:
                if heading is not None:
                    body.extend(
                        DocumentNode(type=PAGE_BREAK)
                        for _ in range(leading_page_breaks)
                    )
                flush()
                current_type = detected
                heading = _heading_node(paragraph, detected)
                body = []
                body.extend(
                    DocumentNode(type=PAGE_BREAK)
                    for _ in range(inline_page_breaks)
                )
                continue
            if heading is None:
                # Content before the first semantic heading is the cover.
                current_type = APASectionType.PRESENTATION
                heading = _block(
                    HEADING_1,
                    "Presentación",
                    section_type=current_type.value,
                )
            node = _paragraph_node(paragraph, style)
            body.extend(
                DocumentNode(type=PAGE_BREAK)
                for _ in range(leading_page_breaks)
            )
            body.append(_imported_node(node, current_type))
            body.extend(
                DocumentNode(type=PAGE_BREAK)
                for _ in range(inline_page_breaks)
            )

        flush()
        if not sections:
            raise DocumentBuildError("The DOCX has no readable content.")
        return sections


def _section_type(
    text: str, style: str, current: APASectionType | None
) -> APASectionType | None:
    normalized = text.casefold()
    names = {
        "presentación": APASectionType.PRESENTATION,
        "presentation": APASectionType.PRESENTATION,
        "índice": APASectionType.INDEX,
        "index": APASectionType.INDEX,
        "table of contents": APASectionType.INDEX,
        "introducción": APASectionType.INTRODUCTION,
        "introduction": APASectionType.INTRODUCTION,
        "conclusión": APASectionType.CONCLUSION,
        "conclusion": APASectionType.CONCLUSION,
        "referencias": APASectionType.SOURCES,
        "references": APASectionType.SOURCES,
        "fuentes": APASectionType.SOURCES,
    }
    is_heading = style in {
        "Heading1",
        "Heading 1",
        "APA Heading 1",
        "APA Heading 1 Plain",
    }
    if normalized in names and is_heading:
        return names[normalized]
    if is_heading and current is None:
        return APASectionType.INTRODUCTION
    return None


def _paragraph_node(paragraph, style: str) -> DocumentNode:
    node_type = PARAGRAPH
    if style in {
        "Heading1",
        "Heading 1",
        "APA Heading 1",
        "APA Heading 1 Plain",
    }:
        node_type = HEADING_1
    elif style in {"Heading2", "Heading 2", "APA Heading 2"}:
        node_type = HEADING_2
    elif style in {"Heading3", "Heading 3", "APA Heading 3"}:
        node_type = HEADING_3
    styles = _paragraph_styles(paragraph)
    children = tuple(_runs(paragraph))
    if style in {"List Bullet", "ListBullet"}:
        item = DocumentNode(type=LIST_ITEM, children=children)
        return DocumentNode(
            type=BULLETED_LIST,
            children=(item,),
            styles=styles,
        )
    if style in {"List Number", "ListNumber"}:
        item = DocumentNode(type=LIST_ITEM, children=children)
        return DocumentNode(
            type=NUMBERED_LIST,
            children=(item,),
            styles=styles,
        )
    return DocumentNode(type=node_type, children=children, styles=styles)


def _runs(paragraph) -> list[DocumentNode]:
    nodes: list[DocumentNode] = []
    for item in paragraph.iter_inner_content():
        if isinstance(item, Hyperlink):
            children: list[DocumentNode] = []
            for run in item.runs:
                children.extend(_run_nodes(run))
            if children and item.url:
                nodes.append(hyperlink_node(children, item.url))
            else:
                nodes.extend(children)
            continue
        nodes.extend(_run_nodes(item))
    return nodes or [DocumentNode(text=paragraph.text or " ")]


def _run_nodes(run) -> list[DocumentNode]:
    if not run.text:
        return []
    marks: list[Mark] = []
    if run.bold:
        marks.append(Mark("bold"))
    if run.italic:
        marks.append(Mark("italic"))
    if run.underline:
        marks.append(Mark("underline"))
    if run.font.strike:
        marks.append(Mark(MARK_STRIKETHROUGH))
    if run.font.color.rgb is not None:
        marks.append(Mark(MARK_COLOR, f"#{run.font.color.rgb}"))
    if run.font.highlight_color is not None:
        color = _HIGHLIGHT_COLORS.get(run.font.highlight_color)
        if color is not None:
            marks.append(Mark(MARK_HIGHLIGHT, color))
    shading = run._r.xpath("./w:rPr/w:shd/@w:fill")
    if shading and shading[0] not in {"auto", "nil"}:
        marks.append(Mark(MARK_BACKGROUND_SHADING, f"#{shading[0]}"))
    if run.font.name:
        marks.append(Mark(MARK_FONT_FAMILY, run.font.name))
    if run.font.size is not None:
        marks.append(Mark(MARK_FONT_SIZE, f"{run.font.size.pt:g}pt"))
    if run.font.superscript:
        marks.append(Mark(MARK_SCRIPT, "superscript"))
    elif run.font.subscript:
        marks.append(Mark(MARK_SCRIPT, "subscript"))
    return [DocumentNode(text=run.text, marks=tuple(marks))]


def _block(
    type_: str, text: str, section_type: str | None = None
) -> DocumentNode:
    return DocumentNode(
        type=type_,
        section_type=section_type,
        children=(DocumentNode(text=text),),
    )


def _heading_node(paragraph, section_type: APASectionType) -> DocumentNode:
    return DocumentNode(
        type=HEADING_1,
        section_type=section_type.value,
        children=tuple(_runs(paragraph)),
        styles=_paragraph_styles(paragraph),
    )


def _imported_node(
    node: DocumentNode, section_type: APASectionType | None
) -> DocumentNode:
    if section_type is not APASectionType.SOURCES:
        return node
    return replace(node, metadata={**node.metadata, "docxImported": True})


def _paragraph(text: str) -> DocumentNode:
    return _block(PARAGRAPH, text or " ")


def _table_node(table) -> DocumentNode:
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            paragraphs = tuple(
                _paragraph_node(p, p.style.name if p.style else "")
                for p in cell.paragraphs
                if p.text.strip()
            )
            cells.append(
                DocumentNode(
                    type=TABLE_CELL,
                    children=paragraphs or (_paragraph(" "),),
                    styles=_cell_styles(cell),
                )
            )
        row_styles = {}
        if row.height is not None:
            row_styles["height"] = f"{row.height.pt:g}pt"
        rows.append(
            DocumentNode(
                type=TABLE_ROW,
                children=tuple(cells),
                styles=row_styles,
            )
        )
    return DocumentNode(
        type=TABLE,
        children=tuple(rows),
        styles=_table_styles(table),
    )


def _table_styles(table) -> dict:
    styles: dict = {}
    alignment = table.alignment
    if alignment is not None:
        value = str(alignment).split()[0].lower()
        if value in {"left", "center", "right"}:
            styles["textAlign"] = value
    widths = [
        f"{column.width.pt:g}pt"
        for column in table.columns
        if column.width is not None
    ]
    if len(widths) == len(table.columns):
        styles["columnWidths"] = widths
    fills = table._tbl.xpath("./w:tblPr/w:shd/@w:fill")
    if fills and fills[0] not in {"auto", "nil"}:
        styles["backgroundColor"] = f"#{fills[0]}"
    return styles


def _cell_styles(cell) -> dict:
    styles: dict = {}
    fills = cell._tc.xpath("./w:tcPr/w:shd/@w:fill")
    if fills and fills[0] not in {"auto", "nil"}:
        styles["backgroundColor"] = f"#{fills[0]}"
    width = cell.width
    if width is not None:
        styles["width"] = f"{width.pt:g}pt"
    return styles


def _iter_blocks(document):
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield "paragraph", Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield "table", Table(child, document)


def _marked_section_type(item) -> APASectionType | None:
    element = getattr(item, "_p", None)
    if element is None:
        element = getattr(item, "_tbl", None)
    value = element.get(_SECTION_ATTR) if element is not None else None
    if value is None:
        return None
    try:
        return APASectionType(value)
    except ValueError:
        return None


def _contains_toc_start(paragraph) -> bool:
    instructions = paragraph._p.xpath(".//w:instrText/text()")
    return any(
        value.strip().upper().startswith("TOC ") for value in instructions
    )


def _contains_field_end(paragraph) -> bool:
    values = paragraph._p.xpath('.//w:fldChar[@w:fldCharType="end"]')
    return bool(values)


def _inline_page_break_count(paragraph) -> int:
    return len(paragraph._p.xpath('.//w:br[@w:type="page"]'))


def _page_break_before_count(paragraph) -> int:
    return int(bool(paragraph._p.xpath("./w:pPr/w:pageBreakBefore")))


def _paragraph_styles(paragraph) -> dict[str, str | float]:
    styles: dict[str, str | float] = {}
    alignment = paragraph.alignment
    if alignment is not None:
        value = str(alignment).split()[0].lower()
        if value == "both":
            value = "justify"
        if value in {"left", "center", "right", "justify"}:
            styles["textAlign"] = value

    paragraph_format = paragraph.paragraph_format
    lengths = {
        "textIndent": paragraph_format.first_line_indent,
        "marginLeft": paragraph_format.left_indent,
        "marginRight": paragraph_format.right_indent,
        "marginTop": paragraph_format.space_before,
        "marginBottom": paragraph_format.space_after,
    }
    for name, length in lengths.items():
        if length is not None:
            styles[name] = f"{length.pt:g}pt"
    spacing = paragraph_format.line_spacing
    if isinstance(spacing, float):
        styles["lineHeight"] = spacing
    elif spacing is not None:
        styles["lineHeight"] = f"{spacing.pt:g}pt"
    return styles
