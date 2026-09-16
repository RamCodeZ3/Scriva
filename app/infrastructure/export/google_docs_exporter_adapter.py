from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from application.dtos.export_result import ExportResult
from application.ports.document_exporter_port import DocumentExporterPort
from domain.entities.document import Document
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import (
    APASectionType,
    normalize_document_styles,
)
from domain.value_objects.document_node import (
    BOOKMARK,
    BULLETED_LIST,
    FIELD,
    HEADING_1,
    HEADING_2,
    HEADING_3,
    HEADING_4,
    HEADING_5,
    HYPERLINK,
    IMAGE,
    IMAGE_INLINE,
    NUMBERED_LIST,
    PAGE_BREAK,
    SECTION_BREAK,
    TAB,
    TABLE,
    TABLE_CELL,
    TABLE_OF_CONTENTS,
    TABLE_ROW,
    DocumentNode,
    Mark,
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

_HEADING_STYLES = {
    HEADING_1: "HEADING_1",
    HEADING_2: "HEADING_2",
    HEADING_3: "HEADING_3",
    HEADING_4: "HEADING_4",
    HEADING_5: "HEADING_5",
}
_BULLET_PRESETS = {
    BULLETED_LIST: "BULLET_DISC_CIRCLE_SQUARE",
    NUMBERED_LIST: "NUMBERED_DECIMAL_ALPHA_ROMAN",
}
_HEADING_DEFAULTS: dict[str, dict[str, Any]] = {
    HEADING_1: {
        "textAlign": "center",
        "spaceBefore": "12pt",
        "spaceAfter": "12pt",
    },
    HEADING_2: {
        "textAlign": "left",
        "spaceBefore": "12pt",
        "spaceAfter": "6pt",
    },
    HEADING_3: {
        "textAlign": "left",
        "spaceBefore": "10pt",
        "spaceAfter": "6pt",
    },
    HEADING_4: {
        "textAlign": "left",
        "marginLeft": "36pt",
        "spaceBefore": "8pt",
        "spaceAfter": "4pt",
    },
    HEADING_5: {
        "textAlign": "left",
        "marginLeft": "36pt",
        "spaceBefore": "8pt",
        "spaceAfter": "4pt",
    },
}
_HEADING_TEXT_DEFAULTS = {
    HEADING_1: {"bold": True},
    HEADING_2: {"bold": True},
    HEADING_3: {"bold": True, "italic": True},
    HEADING_4: {"bold": True},
    HEADING_5: {"bold": True, "italic": True},
}
# Google Docs strips private-use Unicode characters. Keep these sentinels
# ASCII-only so the second pass can always find and replace them.
_TOC_MARKER = "[[SCRIVA_TOC]]"
_NAMED_COLORS = {
    "black": "000000",
    "blue": "0000FF",
    "cyan": "00FFFF",
    "darkblue": "00008B",
    "darkcyan": "008B8B",
    "darkgray": "A9A9A9",
    "darkgreen": "006400",
    "darkmagenta": "8B008B",
    "darkred": "8B0000",
    "darkyellow": "B8860B",
    "gray": "808080",
    "green": "008000",
    "lightgray": "D3D3D3",
    "magenta": "FF00FF",
    "red": "FF0000",
    "white": "FFFFFF",
    "yellow": "FFFF00",
    "amarillo": "FFFF00",
    "azul": "0000FF",
    "blanco": "FFFFFF",
    "gris": "808080",
    "negro": "000000",
    "rojo": "FF0000",
    "verde": "008000",
}


@dataclass(frozen=True)
class _TextSpan:
    start: int
    end: int
    style: dict[str, Any]


@dataclass(frozen=True)
class _NamedSpan:
    start: int
    end: int
    name: str


@dataclass
class _GoogleBlock:
    text: str = ""
    node_type: str | None = None
    styles: dict[str, Any] = field(default_factory=dict)
    spans: list[_TextSpan] = field(default_factory=list)
    named_spans: list[_NamedSpan] = field(default_factory=list)
    bullet_preset: str | None = None
    page_break: bool = False
    image_uri: str | None = None
    source_node: DocumentNode | None = None


class GoogleDocsExporterAdapter(DocumentExporterPort):
    """Create a Google Doc from Scriva's canonical document-node tree."""

    def __init__(self, user_access_token: str) -> None:
        self._credentials = Credentials(token=user_access_token)

    async def export(self, document: Document) -> ExportResult:
        return ExportResult(
            url=await asyncio.to_thread(self._export_sync, document)
        )

    def _export_sync(self, document: Document) -> str:
        service = build("docs", "v1", credentials=self._credentials)
        try:
            created = (
                service.documents()
                .create(body={"title": document.title})
                .execute()
            )
            document_id = created["documentId"]
            blocks = _document_blocks(document)
            requests = self._build_requests(document)
            if requests:
                _batch_update(service, document_id, requests)

            tables = [
                block.source_node
                for block in blocks
                if block.node_type == TABLE and block.source_node
            ]
            if tables:
                # insertTable does not return cell positions. Reading the
                # document after creation is mandatory before filling tables.
                snapshot = _get_document(service, document_id)
                requests = _table_content_requests(
                    snapshot,
                    tables,
                    normalize_document_styles(document.global_style),
                )
                if requests:
                    _batch_update(service, document_id, requests)

            if _needs_second_pass(blocks):
                snapshot = _get_document(service, document_id)
                requests = _second_pass_requests(snapshot, blocks)
                if requests:
                    _batch_update(service, document_id, requests)
        except HttpError as exc:
            raise DocumentBuildError(
                f"Google Docs export failed: {exc}"
            ) from exc
        return f"https://docs.google.com/document/d/{document_id}/edit"

    def _build_requests(self, document: Document) -> list[dict[str, Any]]:
        global_styles = normalize_document_styles(document.global_style)
        requests: list[dict[str, Any]] = []
        for block in reversed(_document_blocks(document)):
            requests.extend(_block_requests(block, global_styles))
        return requests


def _batch_update(
    service: Any, document_id: str, requests: list[dict]
) -> None:
    service.documents().batchUpdate(
        documentId=document_id, body={"requests": requests}
    ).execute()


def _get_document(service: Any, document_id: str) -> dict[str, Any]:
    return service.documents().get(documentId=document_id).execute()


def _document_blocks(document: Document) -> list[_GoogleBlock]:
    blocks: list[_GoogleBlock] = []
    for section in document.sections:
        for index, node in enumerate(section.nodes):
            # The BODY section heading is structural metadata (normally
            # "Development"/"Desarrollo"). Other section headings are
            # visible document content. This mirrors the DOCX exporter.
            if index == 0 and section.section_type is APASectionType.BODY:
                continue
            node_blocks = _node_blocks(node)
            if (
                section.section_type is APASectionType.PRESENTATION
                and node.type not in {PAGE_BREAK, SECTION_BREAK}
            ):
                for block in node_blocks:
                    block.node_type = None
                    block.styles = {
                        "bold": index == 0,
                        "textAlign": "center",
                        **(
                            {
                                "spaceBefore": "180pt",
                                "spaceAfter": "36pt",
                            }
                            if index == 0
                            else {"spaceAfter": "6pt"}
                        ),
                        **block.styles,
                    }
            elif section.section_type is APASectionType.INDEX and index == 0:
                for block in node_blocks:
                    block.node_type = None
                    block.styles = {
                        "bold": True,
                        "textAlign": "center",
                        "spaceBefore": "12pt",
                        "spaceAfter": "12pt",
                        **block.styles,
                    }
            blocks.extend(node_blocks)
    return blocks


def _node_blocks(node: DocumentNode) -> list[_GoogleBlock]:
    if node.type in {PAGE_BREAK, SECTION_BREAK}:
        return [_GoogleBlock(page_break=True)]
    if node.type == TABLE_OF_CONTENTS:
        return [_GoogleBlock(text=_TOC_MARKER, node_type=node.type)]
    if node.type in _HEADING_STYLES and node.metadata.get("meta_only"):
        return []
    if node.type in {IMAGE, IMAGE_INLINE}:
        blocks = [_GoogleBlock(image_uri=node.src)]
        if node.caption:
            blocks.append(_GoogleBlock(text=node.caption, styles=node.styles))
        return blocks
    if node.type in _BULLET_PRESETS:
        return [
            _text_block(child, _BULLET_PRESETS[node.type])
            for child in node.children
        ]
    if node.type == TABLE:
        blocks = [_GoogleBlock(node_type=TABLE, source_node=node)]
        if node.caption:
            blocks.append(_GoogleBlock(text=node.caption, styles=node.styles))
        return blocks
    return [_text_block(node)]


def _text_block(
    node: DocumentNode, bullet_preset: str | None = None
) -> _GoogleBlock:
    text, spans, named_spans = _inline_content(node.children)
    return _GoogleBlock(
        text=text,
        node_type=node.type,
        styles=node.styles,
        spans=spans,
        named_spans=named_spans,
        bullet_preset=bullet_preset,
        source_node=node,
    )


def _inline_content(
    nodes: tuple[DocumentNode, ...],
    link: dict[str, str] | None = None,
) -> tuple[str, list[_TextSpan], list[_NamedSpan]]:
    parts: list[str] = []
    spans: list[_TextSpan] = []
    named: list[_NamedSpan] = []
    length = 0
    for node in nodes:
        if node.text is not None:
            value = node.text
            style = _marks_to_google_style(node.marks)
            if link:
                style["link"] = link
        elif node.type == TAB:
            value, style = "\t", {}
        elif node.type == FIELD:
            value, style = str(node.metadata.get("value", "")), {}
        elif node.type in {HYPERLINK, BOOKMARK}:
            nested_link = link
            if node.type == HYPERLINK:
                url = str(node.metadata.get("url") or "")
                nested_link = {"url": url} if url else link
            value, child_spans, child_named = _inline_content(
                node.children, nested_link
            )
            parts.append(value)
            spans.extend(_shift_span(span, length) for span in child_spans)
            named.extend(_shift_named(span, length) for span in child_named)
            if node.type == BOOKMARK and value:
                named.append(
                    _NamedSpan(length, length + len(value), str(node.id))
                )
            length += len(value)
            continue
        else:
            value, child_spans, child_named = _inline_content(
                node.children, link
            )
            parts.append(value)
            spans.extend(_shift_span(span, length) for span in child_spans)
            named.extend(_shift_named(span, length) for span in child_named)
            length += len(value)
            continue
        parts.append(value)
        if value and style:
            spans.append(_TextSpan(length, length + len(value), style))
        length += len(value)
    return "".join(parts), spans, named


def _shift_span(span: _TextSpan, offset: int) -> _TextSpan:
    return _TextSpan(span.start + offset, span.end + offset, span.style)


def _shift_named(span: _NamedSpan, offset: int) -> _NamedSpan:
    return _NamedSpan(span.start + offset, span.end + offset, span.name)


def _block_requests(
    block: _GoogleBlock, global_styles: dict[str, Any]
) -> list[dict[str, Any]]:
    if block.page_break:
        return [{"insertPageBreak": {"location": {"index": 1}}}]
    if block.image_uri:
        return [
            {
                "insertInlineImage": {
                    "location": {"index": 1},
                    "uri": block.image_uri,
                }
            }
        ]
    if block.node_type == TABLE:
        table = block.source_node
        assert table is not None
        rows = [row for row in table.children if row.type == TABLE_ROW]
        columns = max((len(row.children) for row in rows), default=1)
        return [
            {
                "insertTable": {
                    "rows": max(len(rows), 1),
                    "columns": columns,
                    "location": {"index": 1},
                }
            }
        ]

    inserted = f"{block.text}\n"
    end = 1 + len(inserted)
    requests: list[dict[str, Any]] = [
        {"insertText": {"location": {"index": 1}, "text": inserted}}
    ]
    paragraph_style = _paragraph_style(block, global_styles)
    if paragraph_style:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 1, "endIndex": end},
                    "paragraphStyle": paragraph_style,
                    "fields": ",".join(paragraph_style),
                }
            }
        )
    if block.bullet_preset:
        requests.append(
            {
                "createParagraphBullets": {
                    "range": {"startIndex": 1, "endIndex": end},
                    "bulletPreset": block.bullet_preset,
                }
            }
        )
    base_style = _base_text_style(
        global_styles,
        {
            **_HEADING_TEXT_DEFAULTS.get(block.node_type or "", {}),
            **block.styles,
        },
    )
    if block.text and base_style:
        requests.append(
            _text_style_request(1, 1 + len(block.text), base_style)
        )
    requests.extend(
        _text_style_request(1 + span.start, 1 + span.end, span.style)
        for span in block.spans
        if span.style and span.end > span.start
    )
    requests.extend(
        {
            "createNamedRange": {
                "name": span.name,
                "range": {
                    "startIndex": 1 + span.start,
                    "endIndex": 1 + span.end,
                },
            }
        }
        for span in block.named_spans
        if span.end > span.start
    )
    return requests


def _table_content_requests(
    snapshot: dict[str, Any],
    tables: list[DocumentNode],
    global_styles: dict[str, Any],
) -> list[dict[str, Any]]:
    structures = [
        (item["table"], int(item["startIndex"]))
        for item in snapshot.get("body", {}).get("content", [])
        if "table" in item
    ]
    requests: list[dict[str, Any]] = []
    for table, (structure, table_start) in zip(tables, structures):
        rows = [row for row in table.children if row.type == TABLE_ROW]
        cell_contexts = [
            (row, cell)
            for row in rows
            for cell in row.children
            if cell.type == TABLE_CELL
        ]
        indexed = list(zip(cell_contexts, _cell_indexes(structure)))
        for (row, cell), index in reversed(indexed):
            blocks = [_text_block(child) for child in cell.children]
            text = "\n".join(block.text for block in blocks)
            if not text:
                continue
            requests.append(
                {"insertText": {"location": {"index": index}, "text": text}}
            )
            offset = 0
            for block in blocks:
                resolved_styles = {
                    **table.styles,
                    **row.styles,
                    **cell.styles,
                    **_HEADING_TEXT_DEFAULTS.get(block.node_type or "", {}),
                    **block.styles,
                }
                base = _base_text_style(global_styles, resolved_styles)
                if base and block.text:
                    requests.append(
                        _text_style_request(
                            index + offset,
                            index + offset + len(block.text),
                            base,
                        )
                    )
                requests.extend(
                    _text_style_request(
                        index + offset + span.start,
                        index + offset + span.end,
                        span.style,
                    )
                    for span in block.spans
                    if span.style
                )
                styled_block = _GoogleBlock(
                    node_type=block.node_type,
                    styles=resolved_styles,
                )
                paragraph = _paragraph_style(styled_block, global_styles)
                if paragraph and block.text:
                    requests.append(
                        {
                            "updateParagraphStyle": {
                                "range": {
                                    "startIndex": index + offset,
                                    "endIndex": index
                                    + offset
                                    + len(block.text),
                                },
                                "paragraphStyle": paragraph,
                                "fields": ",".join(paragraph),
                            }
                        }
                    )
                offset += len(block.text) + 1
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row.children):
                background = cell.styles.get(
                    "backgroundColor",
                    row.styles.get(
                        "backgroundColor",
                        table.styles.get("backgroundColor"),
                    ),
                )
                if background is None and row_index == 0 and len(rows) > 1:
                    background = "#F5F5F5"
                color = _color(background)
                if not color:
                    continue
                requests.append(
                    {
                        "updateTableCellStyle": {
                            "tableRange": {
                                "tableCellLocation": {
                                    "tableStartLocation": {
                                        "index": table_start
                                    },
                                    "rowIndex": row_index,
                                    "columnIndex": column_index,
                                },
                                "rowSpan": 1,
                                "columnSpan": 1,
                            },
                            "tableCellStyle": {"backgroundColor": color},
                            "fields": "backgroundColor",
                        }
                    }
                )
    return requests


def _cell_indexes(table: dict[str, Any]) -> list[int]:
    return [
        int(cell["content"][0]["startIndex"])
        for row in table.get("tableRows", [])
        for cell in row.get("tableCells", [])
        if cell.get("content")
    ]


def _needs_second_pass(blocks: list[_GoogleBlock]) -> bool:
    return any(block.node_type == TABLE_OF_CONTENTS for block in blocks)


def _second_pass_requests(
    snapshot: dict[str, Any], blocks: list[_GoogleBlock]
) -> list[dict[str, Any]]:
    runs = _snapshot_paragraphs(snapshot)
    replacements: list[tuple[int, int, str, list[dict[str, Any]]]] = []
    toc_position = _find_marker(runs, _TOC_MARKER)
    if toc_position:
        # Cover and index headings precede the marker and must never list
        # themselves in the generated TOC.
        headings = _snapshot_headings(snapshot, after_index=toc_position[1])
        toc_block = next(
            block for block in blocks if block.node_type == TABLE_OF_CONTENTS
        )
        text = "".join(f"{heading_text}\n" for _, heading_text, _ in headings)
        relative: list[dict[str, Any]] = []
        offset = 0
        for level, heading_text, heading_id in headings:
            end = offset + len(heading_text)
            relative.append(
                _text_style_request(
                    offset, end, {"link": {"headingId": heading_id}}
                )
            )
            relative.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": offset, "endIndex": end + 1},
                        "paragraphStyle": {
                            **_paragraph_style(toc_block, {}),
                            "indentStart": {
                                "magnitude": float((level - 1) * 18),
                                "unit": "PT",
                            },
                        },
                        "fields": ",".join(
                            {
                                *_paragraph_style(toc_block, {}),
                                "indentStart",
                            }
                        ),
                    }
                }
            )
            offset = end + 1
        replacements.append((*toc_position, text, relative))

    requests: list[dict[str, Any]] = []
    for start, end, text, relative in sorted(replacements, reverse=True):
        requests.append(
            {
                "deleteContentRange": {
                    "range": {"startIndex": start, "endIndex": end}
                }
            }
        )
        if text:
            requests.append(
                {"insertText": {"location": {"index": start}, "text": text}}
            )
            requests.extend(_offset_request(item, start) for item in relative)
    return requests


def _snapshot_paragraphs(
    snapshot: dict[str, Any],
) -> list[tuple[int, int, str]]:
    result = []
    for item in snapshot.get("body", {}).get("content", []):
        paragraph = item.get("paragraph")
        if not paragraph:
            continue
        text = "".join(
            element.get("textRun", {}).get("content", "")
            for element in paragraph.get("elements", [])
        )
        result.append((item["startIndex"], item["endIndex"], text))
    return result


def _find_marker(
    runs: list[tuple[int, int, str]], marker: str
) -> tuple[int, int] | None:
    for start, _, text in runs:
        position = text.find(marker)
        if position >= 0:
            marker_start = start + position
            return marker_start, marker_start + len(marker)
    return None


def _snapshot_headings(
    snapshot: dict[str, Any], *, after_index: int = 0
) -> list[tuple[int, str, str]]:
    result = []
    for item in snapshot.get("body", {}).get("content", []):
        if int(item.get("startIndex", 0)) <= after_index:
            continue
        paragraph = item.get("paragraph")
        if not paragraph:
            continue
        style = paragraph.get("paragraphStyle", {})
        named_style = style.get("namedStyleType", "")
        if named_style not in {"HEADING_1", "HEADING_2"}:
            continue
        heading_id = style.get("headingId")
        if not heading_id:
            logger.warning("Google Docs heading has no headingId; omitting it")
            continue
        text = "".join(
            element.get("textRun", {}).get("content", "")
            for element in paragraph.get("elements", [])
        ).rstrip("\n")
        if not text:
            # Empty paragraphs can retain a heading style after page breaks
            # or edits in Google Docs. Linking an empty heading produces an
            # invalid updateTextStyle range (startIndex == endIndex).
            continue
        result.append((int(named_style[-1]), text, heading_id))
    return result


def _offset_request(request: dict[str, Any], offset: int) -> dict[str, Any]:
    operation = next(iter(request))
    payload = {**request[operation]}
    if "range" in payload:
        payload["range"] = {
            **payload["range"],
            "startIndex": payload["range"]["startIndex"] + offset,
            "endIndex": payload["range"]["endIndex"] + offset,
        }
    return {operation: payload}


def _paragraph_style(
    block: _GoogleBlock, global_styles: dict[str, Any]
) -> dict[str, Any]:
    styles = {
        **global_styles,
        **_HEADING_DEFAULTS.get(block.node_type or "", {}),
        **block.styles,
    }
    result: dict[str, Any] = {}
    if block.node_type in _HEADING_STYLES:
        result["namedStyleType"] = _HEADING_STYLES[block.node_type]
    else:
        # Insertions at index 1 inherit the style of the following paragraph.
        # Reset it explicitly or body paragraphs following a heading become
        # headings themselves (and acquire spurious outline bookmarks).
        result["namedStyleType"] = "NORMAL_TEXT"
    alignment = {
        "LEFT": "START",
        "RIGHT": "END",
        "CENTER": "CENTER",
        "JUSTIFY": "JUSTIFIED",
    }.get(str(styles.get("textAlign", "")).upper())
    if alignment:
        result["alignment"] = alignment
    if isinstance(styles.get("lineHeight"), (int, float)):
        result["lineSpacing"] = float(styles["lineHeight"]) * 100
    for source, target in (
        ("spaceBefore", "spaceAbove"),
        ("spaceAfter", "spaceBelow"),
        ("marginLeft", "indentStart"),
        ("textIndent", "indentFirstLine"),
    ):
        if dimension := _dimension(styles.get(source)):
            result[target] = dimension
    return result


def _base_text_style(
    global_styles: dict[str, Any], block_styles: dict[str, Any]
) -> dict[str, Any]:
    styles = {**global_styles, **block_styles}
    result: dict[str, Any] = {}
    family = str(styles.get("fontFamily", "")).split(",", 1)[0].strip()
    if family:
        result["weightedFontFamily"] = {"fontFamily": family}
    if size := _dimension(styles.get("fontSize")):
        result["fontSize"] = size
    if color := _color(styles.get("color")):
        result["foregroundColor"] = color
    for name in ("bold", "italic", "underline", "strikethrough"):
        if name in styles:
            result[name] = bool(styles[name])
    return result


def _marks_to_google_style(marks: tuple[Mark, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mark in marks:
        if mark.type in {"bold", "italic", "underline", "strikethrough"}:
            result[mark.type] = True
        elif mark.type == "fontFamily":
            result["weightedFontFamily"] = {"fontFamily": str(mark.value)}
        elif mark.type == "fontSize" and (value := _dimension(mark.value)):
            result["fontSize"] = value
        elif mark.type == "color" and (value := _color(mark.value)):
            result["foregroundColor"] = value
        elif mark.type in {"highlight", "backgroundShading"}:
            if value := _color(mark.value):
                result["backgroundColor"] = value
            else:
                logger.warning(
                    "Unsupported Google Docs highlight color: %r", mark.value
                )
        elif mark.type == "script":
            result["baselineOffset"] = str(mark.value).upper()
        elif mark.type == "link" and isinstance(mark.value, dict):
            result["link"] = {"url": str(mark.value["url"])}
    return result


def _text_style_request(
    start: int, end: int, style: dict[str, Any]
) -> dict[str, Any]:
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": style,
            "fields": ",".join(style),
        }
    }


def _dimension(value: Any) -> dict[str, Any] | None:
    if isinstance(value, (int, float)):
        return {"magnitude": float(value), "unit": "PT"}
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    for suffix, factor in {"pt": 1.0, "in": 72.0, "px": 0.75}.items():
        if normalized.endswith(suffix):
            try:
                magnitude = float(normalized[: -len(suffix)]) * factor
            except ValueError:
                return None
            return {"magnitude": magnitude, "unit": "PT"}
    return None


def _color(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    raw = _NAMED_COLORS.get(normalized, normalized.lstrip("#"))
    match = re.fullmatch(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})"
        r"(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\)",
        normalized,
    )
    if match:
        values = [int(channel) for channel in match.groups()]
        if any(channel > 255 for channel in values):
            return None
        channels = [channel / 255 for channel in values]
    else:
        if len(raw) == 3:
            raw = "".join(character * 2 for character in raw)
        if len(raw) != 6:
            return None
        try:
            channels = [
                int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)
            ]
        except ValueError:
            return None
    return {
        "color": {
            "rgbColor": {
                "red": channels[0],
                "green": channels[1],
                "blue": channels[2],
            }
        }
    }
