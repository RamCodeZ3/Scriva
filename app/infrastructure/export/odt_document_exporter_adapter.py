from __future__ import annotations

import asyncio
import re
from io import BytesIO
from urllib.request import urlopen

from application.dtos.export_result import ExportResult
from application.ports.document_exporter_port import DocumentExporterPort
from application.services.document_tree_validation import (
    validate_document_tree,
)
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
    DocumentNode,
)
from odf import draw, style, table, text
from odf.opendocument import OpenDocumentText

from infrastructure.export.pdf_document_exporter_adapter import (
    PdfDocumentExporterAdapter,
)

_HEADING_LEVELS = {
    HEADING_1: 1,
    HEADING_2: 2,
    HEADING_3: 3,
    HEADING_4: 4,
    HEADING_5: 5,
}
_HIGHLIGHTS = {
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


class OdtDocumentExporterAdapter(DocumentExporterPort):
    async def export(self, document: Document) -> ExportResult:
        try:
            content = await asyncio.to_thread(self._build_sync, document)
        except Exception as exc:
            raise DocumentBuildError(f"ODT export failed: {exc}") from exc

        return ExportResult(
            url=None,
            file_bytes=content,
            file_name=f"{_safe_filename(document.title)}.odt",
            content_type="application/vnd.oasis.opendocument.text",
        )

    def _build_sync(self, document: Document) -> bytes:
        validate_document_tree(document.to_node_tree())
        toc_entries = PdfDocumentExporterAdapter().build_toc_entries(document)
        odt = OpenDocumentText()
        context = _Context(
            odt, normalize_document_styles(document.global_style)
        )
        context.configure_document()

        self._build_cover(odt, document, context)
        self._build_index(odt, document, context, toc_entries)
        for section_type in (
            APASectionType.INTRODUCTION,
            APASectionType.BODY,
            APASectionType.CONCLUSION,
        ):
            self._build_section(odt, document, section_type, context)
        self._build_references(odt, document, context)

        output = BytesIO()
        odt.save(output)
        return output.getvalue()

    def _build_cover(
        self, odt: OpenDocumentText, document: Document, context: _Context
    ) -> None:
        section = document.get_section(APASectionType.PRESENTATION)
        heading = text.P(stylename=context.named["TitleCover"])
        if section is None:
            heading.addText(document.title)
        else:
            _render_inline(heading, section.heading.children, context)
        odt.text.addElement(heading)

        if section is None:
            _page_break(odt.text, context)
            return
        has_break = False
        for node in section.body_nodes:
            if node.type in {PAGE_BREAK, SECTION_BREAK}:
                _page_break(odt.text, context)
                has_break = True
            else:
                paragraph = text.P(stylename=context.named["CoverLine"])
                _render_inline(paragraph, node.children, context, node.styles)
                odt.text.addElement(paragraph)
        if not has_break:
            _page_break(odt.text, context)

    def _build_index(
        self,
        odt: OpenDocumentText,
        document: Document,
        context: _Context,
        entries: list[tuple[int, str, int, str]],
    ) -> None:
        section = document.get_section(APASectionType.INDEX)
        heading = text.P(stylename=context.named["Heading1Plain"])
        if section is None:
            heading.addText("Índice")
        else:
            _render_inline(heading, section.heading.children, context)
        odt.text.addElement(heading)

        toc_styles = {}
        if section is not None:
            toc_node = next(
                (
                    node
                    for node in section.body_nodes
                    if node.type == "table-of-contents"
                ),
                None,
            )
            if toc_node is not None:
                toc_styles = toc_node.styles
        for level, title, page_number, bookmark in entries:
            paragraph = text.P(
                stylename=context.paragraph_style(
                    {**toc_styles, "marginLeft": f"{level * 18}pt"}
                )
            )
            link = text.A(href=f"#{bookmark}")
            link.addText(title)
            paragraph.addElement(link)
            paragraph.addElement(text.Tab())
            paragraph.addText(str(page_number))
            odt.text.addElement(paragraph)
        _page_break(odt.text, context)

    def _build_section(
        self,
        odt: OpenDocumentText,
        document: Document,
        section_type: APASectionType,
        context: _Context,
    ) -> None:
        section = document.get_section(section_type)
        if section is None:
            return
        if section_type is not APASectionType.BODY:
            _render_heading(odt.text, section.heading, context)
        for node in section.body_nodes:
            _render_block(odt.text, node, context)

    def _build_references(
        self, odt: OpenDocumentText, document: Document, context: _Context
    ) -> None:
        conclusion = document.get_section(APASectionType.CONCLUSION)
        if conclusion is None or conclusion.body_nodes[-1].type != PAGE_BREAK:
            _page_break(odt.text, context)
        section = document.get_section(APASectionType.SOURCES)
        if section is None:
            heading = DocumentNode(
                type=HEADING_1,
                children=(DocumentNode(text="References"),),
            )
        else:
            heading = section.heading
        _render_heading(odt.text, heading, context)

        imported = section is not None and any(
            node.metadata.get("docxImported") for node in section.body_nodes
        )
        if imported and section is not None:
            for node in section.body_nodes:
                if node.type != PAGE_BREAK:
                    _render_block(odt.text, node, context)
            return
        if document.sources:
            for reference in sorted(
                document.sources, key=lambda item: (item.author or "").lower()
            ):
                paragraph = text.P(stylename=context.named["Reference"])
                paragraph.addText(reference.to_apa_string())
                odt.text.addElement(paragraph)
        else:
            paragraph = text.P(stylename=context.named["Body"])
            paragraph.addText("No sources were provided.")
            odt.text.addElement(paragraph)


class _Context:
    def __init__(self, odt: OpenDocumentText, document_styles: dict) -> None:
        self.odt = odt
        self.document_styles = document_styles
        self.named: dict[str, style.Style] = {}
        self._style_sequence = 0
        self._heading_sequence = 0

    def configure_document(self) -> None:
        font = _font_family(self.document_styles.get("fontFamily"))
        size = _length(self.document_styles.get("fontSize"), "12pt")
        color = _color(self.document_styles.get("color"), "#000000")
        line_height = _line_height(self.document_styles.get("lineHeight", 2.0))
        defaults = style.DefaultStyle(family="paragraph")
        defaults.addElement(
            style.TextProperties(fontname=font, fontsize=size, color=color)
        )
        defaults.addElement(style.ParagraphProperties(lineheight=line_height))
        self.odt.styles.addElement(defaults)

        self.named = {
            "TitleCover": self._named_style(
                "TitleCover",
                bold=True,
                align="center",
                margin_top="2.5in",
                margin_bottom="0.5in",
                master_page="Scriva",
            ),
            "CoverLine": self._named_style("CoverLine", align="center"),
            "Heading1": self._named_style(
                "Heading1",
                bold=True,
                align="center",
                margin_top="12pt",
                margin_bottom="12pt",
            ),
            "Heading1Plain": self._named_style(
                "Heading1Plain",
                bold=True,
                align="center",
                margin_top="12pt",
                margin_bottom="12pt",
            ),
            "Heading2": self._named_style(
                "Heading2", bold=True, margin_top="12pt", margin_bottom="6pt"
            ),
            "Heading3": self._named_style(
                "Heading3",
                bold=True,
                italic=True,
                margin_top="10pt",
                margin_bottom="6pt",
            ),
            "Heading4": self._named_style(
                "Heading4",
                bold=True,
                margin_left="36pt",
                margin_top="8pt",
                margin_bottom="4pt",
            ),
            "Heading5": self._named_style(
                "Heading5",
                bold=True,
                italic=True,
                margin_left="36pt",
                margin_top="8pt",
                margin_bottom="4pt",
            ),
            "Body": self._named_style(
                "Body", align="justify", text_indent="36pt"
            ),
            "BlockQuote": self._named_style(
                "BlockQuote",
                align="justify",
                margin_left="36pt",
                margin_right="36pt",
                margin_top="6pt",
                margin_bottom="6pt",
            ),
            "Reference": self._named_style(
                "Reference",
                margin_left="36pt",
                text_indent="-36pt",
                margin_bottom="12pt",
            ),
            "Caption": self._named_style(
                "Caption",
                italic=True,
                align="center",
                margin_top="4pt",
                margin_bottom="12pt",
            ),
            "PageBreak": self._named_style("PageBreak", break_before="page"),
        }
        self._configure_page_layout()
        self._configure_list_styles()

    def _named_style(self, name: str, **properties) -> style.Style:
        master_page = properties.pop("master_page", None)
        item = style.Style(
            name=name,
            family="paragraph",
            masterpagename=master_page,
        )
        item.addElement(
            style.TextProperties(
                fontweight="bold" if properties.pop("bold", False) else None,
                fontstyle="italic"
                if properties.pop("italic", False)
                else None,
            )
        )
        item.addElement(
            style.ParagraphProperties(**_odf_paragraph(properties))
        )
        self.odt.styles.addElement(item)
        return item

    def paragraph_style(
        self, values: dict, parent: str = "Body"
    ) -> style.Style:
        self._style_sequence += 1
        item = style.Style(
            name=f"Paragraph{self._style_sequence}",
            family="paragraph",
            parentstylename=self.named[parent],
        )
        item.addElement(style.ParagraphProperties(**_block_properties(values)))
        item.addElement(style.TextProperties(**_text_properties(values)))
        self.odt.automaticstyles.addElement(item)
        return item

    def text_style(self, values: dict) -> style.Style:
        self._style_sequence += 1
        item = style.Style(name=f"Text{self._style_sequence}", family="text")
        item.addElement(style.TextProperties(**_text_properties(values)))
        self.odt.automaticstyles.addElement(item)
        return item

    def next_bookmark(self) -> str:
        self._heading_sequence += 1
        return f"toc-heading-{self._heading_sequence}"

    def _configure_page_layout(self) -> None:
        page_width, page_height = _page_size(self.document_styles)
        if self.document_styles.get("orientation") == "landscape":
            page_width, page_height = page_height, page_width
        margins = self.document_styles["pageMargin"]
        layout = style.PageLayout(name="ScrivaPage")
        layout.addElement(
            style.PageLayoutProperties(
                pagewidth=page_width,
                pageheight=page_height,
                printorientation=self.document_styles.get(
                    "orientation", "portrait"
                ),
                margintop=_length(margins.get("top"), "1in"),
                marginbottom=_length(margins.get("bottom"), "1in"),
                marginleft=_length(margins.get("left"), "1in"),
                marginright=_length(margins.get("right"), "1in"),
                backgroundcolor=_color(
                    self.document_styles.get("backgroundColor"), "#FFFFFF"
                ),
            )
        )
        self.odt.automaticstyles.addElement(layout)
        master = style.MasterPage(name="Scriva", pagelayoutname=layout)
        if self.document_styles.get("showPageNumbers", True):
            position = self.document_styles["pageNumberPosition"]
            container = (
                style.Footer()
                if position.startswith("bottom")
                else style.Header()
            )
            align = "center" if position.endswith("center") else "right"
            paragraph = text.P(
                stylename=self.paragraph_style({"textAlign": align})
            )
            paragraph.addElement(text.PageNumber(selectpage="current"))
            container.addElement(paragraph)
            master.addElement(container)
        self.odt.masterstyles.addElement(master)

    def _configure_list_styles(self) -> None:
        bullet = text.ListStyle(name="BulletList")
        bullet.addElement(text.ListLevelStyleBullet(level=1, bulletchar="•"))
        numbered = text.ListStyle(name="NumberedList")
        numbered.addElement(
            text.ListLevelStyleNumber(
                level=1,
                numformat="1",
                numsuffix=".",
            )
        )
        self.odt.styles.addElement(bullet)
        self.odt.styles.addElement(numbered)
        self.named["BulletList"] = bullet
        self.named["NumberedList"] = numbered


def _render_heading(container, node: DocumentNode, context: _Context) -> None:
    level = _HEADING_LEVELS[node.type]
    heading = text.H(
        outlinelevel=level,
        stylename=context.paragraph_style(node.styles, f"Heading{level}"),
    )
    bookmark = context.next_bookmark()
    heading.addElement(text.BookmarkStart(name=bookmark))
    _render_inline(heading, node.children, context, node.styles)
    heading.addElement(text.BookmarkEnd(name=bookmark))
    container.addElement(heading)


def _render_block(
    container,
    node: DocumentNode,
    context: _Context,
    inherited_styles: dict | None = None,
) -> None:
    resolved = {**(inherited_styles or {}), **node.styles}
    if node.type in {PAGE_BREAK, SECTION_BREAK}:
        _page_break(container, context)
    elif node.type in _HEADING_LEVELS:
        _render_heading(container, node, context)
    elif node.type in {PARAGRAPH, BLOCK_QUOTE}:
        parent = "BlockQuote" if node.type == BLOCK_QUOTE else "Body"
        paragraph = text.P(stylename=context.paragraph_style(resolved, parent))
        _render_inline(paragraph, node.children, context, resolved)
        container.addElement(paragraph)
    elif node.type in {BULLETED_LIST, NUMBERED_LIST}:
        list_style = (
            context.named["BulletList"]
            if node.type == BULLETED_LIST
            else context.named["NumberedList"]
        )
        rendered = text.List(stylename=list_style)
        for item in node.children:
            list_item = text.ListItem()
            paragraph = text.P(
                stylename=context.paragraph_style(
                    {**resolved, **item.styles}, "Body"
                )
            )
            _render_inline(paragraph, item.children, context, resolved)
            list_item.addElement(paragraph)
            rendered.addElement(list_item)
        container.addElement(rendered)
    elif node.type == TABLE:
        _render_table(container, node, context, resolved)
    elif node.type == IMAGE:
        _render_image(container, node, context)
    else:
        raise DocumentBuildError(
            f"Unsupported block node in section: '{node.type}'"
        )


def _render_inline(
    paragraph,
    nodes: tuple[DocumentNode, ...],
    context: _Context,
    inherited_styles: dict | None = None,
) -> None:
    for node in nodes:
        if node.type == TAB:
            paragraph.addElement(text.Tab())
            continue
        if node.type == FIELD:
            paragraph.addText(f"{{{node.field_type}}}")
            continue
        if node.type == HYPERLINK:
            link = text.A(href=str(node.metadata.get("url", "")))
            _render_inline(link, node.children, context, inherited_styles)
            paragraph.addElement(link)
            continue
        if node.text is None:
            raise DocumentBuildError(
                f"Expected inline text, got '{node.type}'."
            )
        values = {
            **(inherited_styles or {}),
            **{
                mark.type: True if mark.value is None else mark.value
                for mark in node.marks
            },
        }
        link_value = values.pop("link", None)
        span = text.Span(stylename=context.text_style(values))
        span.addText(node.text)
        if isinstance(link_value, dict) and link_value.get("url"):
            link = text.A(href=str(link_value["url"]))
            link.addElement(span)
            paragraph.addElement(link)
        else:
            paragraph.addElement(span)


def _render_table(
    container, node: DocumentNode, context: _Context, inherited: dict
) -> None:
    rendered = table.Table()
    for row_index, row_node in enumerate(node.children):
        row = table.TableRow()
        for cell_node in row_node.children:
            cell_values = {**inherited, **row_node.styles, **cell_node.styles}
            cell_style = style.Style(
                name=f"TableCell{context._style_sequence}", family="table-cell"
            )
            context._style_sequence += 1
            background = cell_values.get("backgroundColor")
            if (
                background is None
                and row_index == 0
                and len(node.children) > 1
            ):
                background = "#F5F5F5"
            cell_style.addElement(
                style.TableCellProperties(
                    border="0.75pt solid #000000",
                    backgroundcolor=_color(background, "transparent"),
                    padding="3pt",
                )
            )
            context.odt.automaticstyles.addElement(cell_style)
            cell = table.TableCell(
                stylename=cell_style,
                numbercolumnsspanned=cell_node.col_span,
                numberrowsspanned=cell_node.row_span,
            )
            for child in cell_node.children:
                _render_block(cell, child, context, cell_values)
            row.addElement(cell)
        rendered.addElement(row)
    container.addElement(rendered)
    if node.caption:
        caption = text.P(stylename=context.named["Caption"])
        caption.addText(node.caption)
        container.addElement(caption)


def _render_image(container, node: DocumentNode, context: _Context) -> None:
    paragraph = text.P(
        stylename=context.paragraph_style(
            {"textAlign": node.styles.get("textAlign", "center")}
        )
    )
    try:
        with urlopen(node.src, timeout=10) as response:  # noqa: S310
            content = response.read()
            media_type = response.headers.get_content_type()
        href = context.odt.addPictureFromString(content, media_type)
        frame = draw.Frame(
            width=_length(node.styles.get("width"), "6.5in"),
            anchortype="as-char",
        )
        frame.addElement(draw.Image(href=href))
        paragraph.addElement(frame)
    except Exception:
        paragraph.addText(
            f"[Image unavailable: {node.alt or node.caption or node.src}]"
        )
    container.addElement(paragraph)
    if node.caption:
        caption = text.P(stylename=context.named["Caption"])
        caption.addText(node.caption)
        container.addElement(caption)


def _page_break(container, context: _Context) -> None:
    container.addElement(text.P(stylename=context.named["PageBreak"]))


def _text_properties(values: dict) -> dict:
    properties: dict = {}
    if values.get("bold"):
        properties["fontweight"] = "bold"
    if values.get("italic"):
        properties["fontstyle"] = "italic"
    if values.get("underline"):
        properties.update(
            textunderlinestyle="solid", textunderlinewidth="auto"
        )
    if values.get("strikethrough"):
        properties["textlinethroughstyle"] = "solid"
    if values.get("code"):
        properties["fontname"] = "Courier New"
    if values.get("fontFamily"):
        properties["fontname"] = _font_family(values["fontFamily"])
    if values.get("fontSize"):
        properties["fontsize"] = _length(values["fontSize"], "12pt")
    if values.get("color"):
        properties["color"] = _color(values["color"], "#000000")
    highlight = values.get("backgroundShading", values.get("highlight"))
    if highlight and highlight != "none":
        properties["backgroundcolor"] = _color(
            _HIGHLIGHTS.get(str(highlight), highlight), "transparent"
        )
    script = values.get("script")
    if script == "superscript":
        properties["textposition"] = "super 58%"
    elif script == "subscript":
        properties["textposition"] = "sub 58%"
    return properties


def _block_properties(values: dict) -> dict:
    properties = _odf_paragraph(
        {
            "align": values.get("textAlign"),
            "text_indent": _length(values.get("textIndent"), None),
            "margin_top": _length(values.get("spaceBefore"), None),
            "margin_bottom": _length(values.get("marginBottom"), None),
            "margin_left": _length(values.get("marginLeft"), None),
            "margin_right": _length(values.get("marginRight"), None),
        }
    )
    if values.get("lineHeight") is not None:
        properties["lineheight"] = _line_height(values["lineHeight"])
    if values.get("backgroundColor"):
        properties["backgroundcolor"] = _color(
            values["backgroundColor"], "transparent"
        )
    if values.get("borderLeft"):
        properties["borderleft"] = str(values["borderLeft"])
    return properties


def _odf_paragraph(values: dict) -> dict:
    mapping = {
        "align": "textalign",
        "text_indent": "textindent",
        "margin_top": "margintop",
        "margin_bottom": "marginbottom",
        "margin_left": "marginleft",
        "margin_right": "marginright",
        "break_before": "breakbefore",
    }
    return {
        mapping[key]: value
        for key, value in values.items()
        if value is not None
    }


def _font_family(value) -> str:
    return str(value or "Times New Roman").split(",", 1)[0].strip(" '\"")


def _length(value, default: str | None) -> str | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return f"{value}pt"
    raw = str(value).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return f"{raw}pt"
    return raw


def _line_height(value) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value) * 100:g}%"
    raw = str(value)
    if raw.endswith(("pt", "%", "in", "cm", "mm")):
        return raw
    try:
        return f"{float(raw) * 100:g}%"
    except ValueError:
        return "200%"


def _color(value, default: str) -> str:
    if value is None:
        return default
    raw = str(value).strip()
    if raw == "transparent":
        return raw
    return raw if raw.startswith("#") else f"#{raw}"


def _page_size(document_styles: dict) -> tuple[str, str]:
    raw = document_styles.get("pageSize", "letter")
    if isinstance(raw, dict):
        return (
            _length(raw.get("width"), "8.5in") or "8.5in",
            _length(raw.get("height"), "11in") or "11in",
        )
    if str(raw).lower() == "a4":
        return "210mm", "297mm"
    return "8.5in", "11in"


def _safe_filename(title: str) -> str:
    return re.sub(r"[^\w\-. ]", "_", title).strip() or "document"
