from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.entities.source import Source
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import (
    APA7_DOCUMENT_STYLES,
    APASection,
    APASectionType,
    normalize_document_styles,
)
from domain.value_objects.document_node import (
    PAGE_BREAK,
    SECTION_BREAK,
    DocumentNode,
)
from domain.value_objects.document_type import DocumentType
from domain.value_objects.source_ref import SourceReference


@dataclass(frozen=True)
class SourceInput:
    raw: str
    source_type: str
    lang: str = "en"


class DocumentStatus(Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    GENERATING = "generating"
    EXPANDING = "expanding"
    DRAFTING = "drafting"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Document:
    id: UUID
    user_id: UUID
    title: str
    document_type: DocumentType
    raw_sources: list[Source]
    status: DocumentStatus
    sections: list[APASection]
    sources: list[SourceReference]
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None
    error_stage: str | None = None
    global_style: dict[str, Any] = field(
        default_factory=lambda: dict(APA7_DOCUMENT_STYLES)
    )
    numbering_definitions: dict[str, Any] = field(default_factory=dict)
    headers_footers: dict[str, Any] = field(
        default_factory=lambda: {
            "default_header": {"children": []},
            "default_footer": {"children": []},
            "first_page_different": False,
        }
    )

    @classmethod
    def create(
        cls,
        user_id: UUID,
        title: str,
        document_type: DocumentType,
        raw_sources: list[Source],
    ) -> Document:
        if not raw_sources:
            raise DocumentBuildError("A document needs at least one source.")

        now = datetime.utcnow()
        return cls(
            id=uuid4(),
            user_id=user_id,
            title=title,
            document_type=document_type,
            raw_sources=raw_sources,
            status=DocumentStatus.PENDING,
            sections=[],
            sources=[],
            created_at=now,
            updated_at=now,
        )

    def start_extraction(self) -> None:
        self._assert_status(DocumentStatus.PENDING)
        self.status = DocumentStatus.EXTRACTING
        self._touch()

    def start_generation(self) -> None:
        self._assert_status(DocumentStatus.EXTRACTING)
        self.status = DocumentStatus.GENERATING
        self._touch()

    def start_expansion(self) -> None:
        self._assert_status(DocumentStatus.EXTRACTING)
        self.status = DocumentStatus.EXPANDING
        self._touch()

    def start_drafting(self) -> None:
        if self.status not in {
            DocumentStatus.GENERATING,
            DocumentStatus.EXPANDING,
        }:
            raise DocumentBuildError(
                "Invalid operation: document is "
                f"'{self.status.value}', expected 'generating' or "
                "'expanding'."
            )
        self.status = DocumentStatus.DRAFTING
        self._touch()

    def complete(
        self,
        title: str,
        sections: list[APASection],
        sources: list[SourceReference],
        global_style: dict[str, Any] | None = None,
    ) -> None:
        self._assert_status(DocumentStatus.DRAFTING)
        self._validate_sections(sections)

        self.title = title
        self.sections = sorted(sections, key=lambda s: s.section_type.order)
        self.sources = sources
        if global_style is not None:
            self.global_style = global_style
        self.status = DocumentStatus.DONE
        self._touch()

    def update_content(
        self,
        title: str | None = None,
        sections: list[APASection] | None = None,
        global_style: dict[str, Any] | None = None,
    ) -> None:
        if title is not None:
            self.title = title
        if sections is not None:
            self.sections = sorted(
                sections, key=lambda s: s.section_type.order
            )
        if global_style is not None:
            self.global_style = global_style
        self._touch()

    def augment(
        self,
        title: str,
        sections: list[APASection],
        sources: list[SourceReference],
        new_raw_sources: list[Source],
    ) -> None:
        if self.status != DocumentStatus.DRAFTING:
            raise DocumentBuildError(
                "Cannot add info to a document in "
                f"'{self.status.value}' status; "
                "it must be 'drafting'."
            )
        self._validate_sections(sections)
        self.title = title
        self.sections = sorted(sections, key=lambda s: s.section_type.order)
        self.sources = sources
        existing_ids = {source.id for source in self.raw_sources}
        self.raw_sources.extend(
            source
            for source in new_raw_sources
            if source.id not in existing_ids
        )
        self.status = DocumentStatus.DONE
        self.error_message = None
        self.error_stage = None
        self._touch()

    def start_augmentation(self, new_raw_sources: list[Source]) -> None:
        self._assert_status(DocumentStatus.DONE)
        self.raw_sources.extend(new_raw_sources)
        self.status = DocumentStatus.EXTRACTING
        self.error_message = None
        self.error_stage = None
        self._touch()

    def fail(self, reason: str, stage: str | None = None) -> None:
        self.status = DocumentStatus.FAILED
        self.error_message = reason
        self.error_stage = stage
        self._touch()

    def is_ready(self) -> bool:
        return self.status == DocumentStatus.DONE

    def get_section(self, section_type: APASectionType) -> APASection | None:
        return next(
            (s for s in self.sections if s.section_type == section_type), None
        )

    def to_node_tree(self) -> dict[str, Any]:
        """Serialize the complete document as its canonical node tree.

        Global styles are root metadata and never content children. A block's
        ``styles`` and a text leaf's ``marks`` remain local overrides.
        """
        children: list[dict[str, Any]] = []
        for section in self.sections:
            children.append(
                _root_node_dict(section.heading, section.section_type.value)
            )
            children.extend(
                _root_node_dict(node, section.section_type.value)
                for node in section.body_nodes
            )

        return {
            "type": "document",
            "meta": {
                "title": self.title,
                "style_guide": "APA7",
                "version": "2.0",
            },
            "global_style": normalize_document_styles(self.global_style),
            "numbering_definitions": dict(self.numbering_definitions),
            "headers_footers": dict(self.headers_footers),
            "children": children,
        }

    def _validate_sections(self, sections: list[APASection]) -> None:
        if not sections:
            raise DocumentBuildError(
                "A document must have at least one section."
            )
        required = {
            APASectionType.PRESENTATION,
            APASectionType.INDEX,
            APASectionType.INTRODUCTION,
            APASectionType.BODY,
            APASectionType.CONCLUSION,
            APASectionType.SOURCES,
        }
        missing = required - {s.section_type for s in sections}
        if missing:
            names = ", ".join(m.value for m in missing)
            raise DocumentBuildError(f"Missing required APA sections: {names}")

    def _assert_status(self, expected: DocumentStatus) -> None:
        if self.status != expected:
            raise DocumentBuildError(
                f"Invalid operation: document is '{self.status.value}', "
                f"expected '{expected.value}'."
            )

    def _touch(self) -> None:
        self.updated_at = datetime.utcnow()


def _root_node_dict(node: DocumentNode, section_type: str) -> dict[str, Any]:
    data = node.to_dict()
    if node.type in {PAGE_BREAK, SECTION_BREAK}:
        data.pop("section_type", None)
    else:
        data["section_type"] = section_type
    return data
