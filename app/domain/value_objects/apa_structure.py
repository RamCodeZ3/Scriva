from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from domain.value_objects.document_node import (
    HEADING_1,
    PAGE_NUMBER_POSITIONS,
    DocumentNode,
)


class APASectionType(Enum):
    """Canonical APA 7 section order."""

    PRESENTATION = "presentation"
    INDEX = "index"
    INTRODUCTION = "introduction"
    BODY = "body"
    CONCLUSION = "conclusion"
    SOURCES = "sources"

    @property
    def order(self) -> int:
        return {
            "PRESENTATION": 1,
            "INDEX": 2,
            "INTRODUCTION": 3,
            "BODY": 4,
            "CONCLUSION": 5,
            "SOURCES": 6,
        }[self.name]


APA7_DOCUMENT_STYLES: dict[str, Any] = {
    "fontFamily": "Times New Roman, serif",
    "fontSize": "12pt",
    "color": "#000000",
    "backgroundColor": "#ffffff",
    "pageMargin": {
        "top": "1in",
        "right": "1in",
        "bottom": "1in",
        "left": "1in",
    },
    "pageSize": "letter",
    "orientation": "portrait",
    "lineHeight": 2.0,
    "showPageNumbers": True,
    "pageNumberPosition": "top-right",
}


def normalize_document_styles(
    document_styles: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge user/document-level overrides on top of the APA 7 defaults,
    normalizing the foliation fields so the exporter never has to guard
    against a bad or unknown 'pageNumberPosition'."""
    merged = {**APA7_DOCUMENT_STYLES, **(document_styles or {})}

    position = str(merged.get("pageNumberPosition", "top-right")).lower()
    if position not in PAGE_NUMBER_POSITIONS:
        position = "top-right"
    merged["pageNumberPosition"] = position
    merged["showPageNumbers"] = bool(merged.get("showPageNumbers", True))
    page_margin = merged.get("pageMargin")
    if isinstance(page_margin, str):
        merged["pageMargin"] = {
            side: page_margin for side in ("top", "right", "bottom", "left")
        }
    return merged


@dataclass(frozen=True)
class APASection:
    """A logical APA section: its heading node plus the block nodes
    (paragraphs, subheadings, lists, images) that make up its body, in
    order."""

    section_type: APASectionType
    heading: DocumentNode
    body_nodes: tuple[DocumentNode, ...] = ()

    def __post_init__(self) -> None:
        if self.heading.type != HEADING_1:
            raise ValueError(
                f"Section '{self.section_type.value}' heading must be a "
                f"'{HEADING_1}' node."
            )
        if not self.heading.plain_text().strip():
            raise ValueError(
                f"Section '{self.section_type.value}' must have a title."
            )
        if not self.body_nodes:
            raise ValueError(
                f"Section '{self.section_type.value}' cannot be empty."
            )

    @property
    def title(self) -> str:
        return self.heading.plain_text()

    @property
    def nodes(self) -> tuple[DocumentNode, ...]:
        """Heading followed by body nodes, in document order."""
        return (self.heading,) + self.body_nodes
