from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from application.dtos.export_result import ExportResult
from application.ports.document_exporter_port import DocumentExporterPort
from domain.entities.document import Document
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import normalize_document_styles
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


@dataclass(frozen=True)
class _TextSpan:
    start: int
    end: int
    style: dict[str, Any]


@dataclass
class _GoogleBlock:
    text: str = ""
    node_type: str | None = None
    styles: dict[str, Any] = field(default_factory=dict)
    spans: list[_TextSpan] = field(default_factory=list)
    bullet_preset: str | None = None
    page_break: bool = False
    image_uri: str | None = None


class GoogleDocsExporterAdapter(DocumentExporterPort):
    """Create a Google Doc from Scriva's canonical document-node tree."""

    def __init__(self, user_access_token: str) -> None:
        self._credentials = Credentials(token=user_access_token)

    async def export(self, document: Document) -> ExportResult:
        url = await asyncio.to_thread(self._export_sync, document)
        return ExportResult(url=url)

    def _export_sync(self, document: Document) -> str:
        docs_service = build("docs", "v1", credentials=self._credentials)
        try:
            created = (
                docs_service.documents()
                .create(body={"title": document.title})
                .execute()
            )
            document_id = created["documentId"]
            requests = self._build_requests(document)
            if requests:
                docs_service.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()
        except HttpError as exc:
            raise DocumentBuildError(
                f"Google Docs export failed: {exc}"
            ) from exc
        return f"https://docs.google.com/document/d/{document_id}/edit"

    def _build_requests(self, document: Document) -> list[dict]:
        """Translate the persisted node tree into Google Docs mutations."""
        global_styles = normalize_document_styles(document.global_style)
        requests: list[dict] = []
        for block in reversed(_document_blocks(document)):
            requests.extend(_block_requests(block, global_styles))
        return requests


def _document_blocks(document: Document) -> list[_GoogleBlock]:
    blocks: list[_GoogleBlock] = []
    for section in document.sections:
        for node in section.nodes:
            blocks.extend(_node_blocks(node))
    return blocks


def _node_blocks(node: DocumentNode) -> list[_GoogleBlock]:
    if node.type in {PAGE_BREAK, SECTION_BREAK}:
        return [_GoogleBlock(page_break=True)]
    if node.type == TABLE_OF_CONTENTS:
        # Google Docs API has no request for creating a native TOC. Its
        # heading and following page break are independent tree nodes.
        return []
    if node.type in {IMAGE, IMAGE_INLINE}:
        blocks = [_GoogleBlock(image_uri=node.src)]
        if node.caption:
            blocks.append(_GoogleBlock(text=node.caption, styles=node.styles))
        return blocks
    if node.type in _BULLET_PRESETS:
        return [
            _text_block(child, bullet_preset=_BULLET_PRESETS[node.type])
            for child in node.children
        ]
    if node.type == TABLE:
        return [_table_block(node)]
    return [_text_block(node)]


def _text_block(
    node: DocumentNode, *, bullet_preset: str | None = None
) -> _GoogleBlock:
    text, spans = _inline_content(node.children)
    return _GoogleBlock(
        text=text,
        node_type=node.type,
        styles=node.styles,
        spans=spans,
        bullet_preset=bullet_preset,
    )


def _table_block(table: DocumentNode) -> _GoogleBlock:
    rows = [
        "\t".join(
            cell.plain_text()
            for cell in row.children
            if cell.type == TABLE_CELL
        )
        for row in table.children
        if row.type == TABLE_ROW
    ]
    text = "\n".join(rows)
    if table.caption:
        text = f"{text}\n{table.caption}" if text else table.caption
    return _GoogleBlock(text=text, node_type=TABLE, styles=table.styles)


def _inline_content(
    nodes: tuple[DocumentNode, ...], link: str | None = None
) -> tuple[str, list[_TextSpan]]:
    parts: list[str] = []
    spans: list[_TextSpan] = []
    length = 0
    for node in nodes:
        if node.text is not None:
            value = node.text
            style = _marks_to_google_style(node.marks)
            if link:
                style["link"] = {"url": link}
        elif node.type == TAB:
            value, style = "\t", {}
        elif node.type == FIELD:
            value, style = str(node.metadata.get("value", "")), {}
        elif node.type in {HYPERLINK, BOOKMARK}:
            nested_link = link
            if node.type == HYPERLINK:
                nested_link = str(node.metadata.get("url") or "") or link
            value, nested = _inline_content(node.children, nested_link)
            parts.append(value)
            spans.extend(
                _TextSpan(
                    length + span.start,
                    length + span.end,
                    span.style,
                )
                for span in nested
            )
            length += len(value)
            continue
        elif node.type == IMAGE_INLINE:
            value, style = node.alt or "", {}
        else:
            value, nested = _inline_content(node.children, link)
            parts.append(value)
            spans.extend(
                _TextSpan(
                    length + span.start,
                    length + span.end,
                    span.style,
                )
                for span in nested
            )
            length += len(value)
            continue
        parts.append(value)
        if value and style:
            spans.append(_TextSpan(length, length + len(value), style))
        length += len(value)
    return "".join(parts), spans


def _block_requests(
    block: _GoogleBlock, global_styles: dict[str, Any]
) -> list[dict]:
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

    inserted_text = f"{block.text}\n"
    end_index = 1 + len(inserted_text)
    requests: list[dict] = [
        {"insertText": {"location": {"index": 1}, "text": inserted_text}}
    ]
    paragraph_style = _paragraph_style(block, global_styles)
    if paragraph_style:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 1, "endIndex": end_index},
                    "paragraphStyle": paragraph_style,
                    "fields": ",".join(paragraph_style),
                }
            }
        )
    if block.bullet_preset:
        requests.append(
            {
                "createParagraphBullets": {
                    "range": {"startIndex": 1, "endIndex": end_index},
                    "bulletPreset": block.bullet_preset,
                }
            }
        )
    base_style = _base_text_style(global_styles, block.styles)
    if block.text and base_style:
        requests.append(
            _text_style_request(1, 1 + len(block.text), base_style)
        )
    requests.extend(
        _text_style_request(1 + span.start, 1 + span.end, span.style)
        for span in block.spans
        if span.style and span.end > span.start
    )
    return requests


def _paragraph_style(
    block: _GoogleBlock, global_styles: dict[str, Any]
) -> dict[str, Any]:
    styles = {**global_styles, **block.styles}
    result: dict[str, Any] = {}
    if block.node_type in _HEADING_STYLES:
        result["namedStyleType"] = _HEADING_STYLES[block.node_type]
    alignment = str(styles.get("textAlign", "")).upper()
    result_alignment = {
        "LEFT": "START",
        "RIGHT": "END",
        "CENTER": "CENTER",
        "JUSTIFY": "JUSTIFIED",
    }.get(alignment)
    if result_alignment:
        result["alignment"] = result_alignment
    line_height = styles.get("lineHeight")
    if isinstance(line_height, (int, float)):
        result["lineSpacing"] = float(line_height) * 100
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
        elif mark.type in {"highlight", "backgroundShading"} and (
            value := _color(mark.value)
        ):
            result["backgroundColor"] = value
        elif mark.type == "script":
            result["baselineOffset"] = str(mark.value).upper()
        elif mark.type == "link" and isinstance(mark.value, dict):
            result["link"] = {"url": str(mark.value["url"])}
    return result


def _text_style_request(start: int, end: int, style: dict[str, Any]) -> dict:
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
    raw = value.strip().lstrip("#")
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
