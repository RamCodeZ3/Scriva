from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from domain.entities.document import Document, DocumentStatus
from domain.entities.source import Source, SourceStatus
from domain.value_objects.apa_structure import APASection
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from domain.value_objects.source_ref import SourceReference


@dataclass(frozen=True)
class SourceErrorOutput:
    """Detail of a single source that failed extraction."""

    source_id: UUID
    raw: str
    error: str


def build_source_errors(raw_sources: list[Source]) -> list[SourceErrorOutput]:
    return [
        SourceErrorOutput(
            source_id=s.id,
            raw=s.raw,
            error=s.error_message or "Unknown extraction error.",
        )
        for s in raw_sources
        if s.status == SourceStatus.FAILED
    ]


@dataclass(frozen=True)
class CreateDocumentInput:
    user_id: UUID
    title: str
    document_type: DocumentType
    presentation: PresentationInfo
    sources: list[str]
    additional_notes: str | None = None


@dataclass(frozen=True)
class CreateDocumentOutput:
    document_id: UUID
    status: DocumentStatus
    document_type: DocumentType
    document_title: str
    sections: list[APASection]
    error_message: str | None = None


@dataclass(frozen=True)
class DocumentOutput:
    id: UUID
    title: str
    document_type: DocumentType
    status: DocumentStatus
    sections: list[APASection]
    user_id: UUID
    presentation: PresentationInfo
    error_message: str | None
    source_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
    source_errors: list[SourceErrorOutput] = field(default_factory=list)


DocumentProgressCallback = Callable[[DocumentOutput], Awaitable[None]]


def document_to_output(document: Document) -> DocumentOutput:
    return DocumentOutput(
        id=document.id,
        title=document.title,
        document_type=document.document_type,
        status=document.status,
        sections=document.sections,
        user_id=document.user_id,
        presentation=document.presentation,
        error_message=document.error_message,
        source_ids=[source.id for source in document.raw_sources],
        source_errors=build_source_errors(document.raw_sources),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@dataclass(frozen=True)
class DocumentFileOutput:
    document: DocumentOutput
    file_bytes: bytes
    file_name: str
    content_type: str


@dataclass(frozen=True)
class UpdateDocumentInput:
    document_id: UUID
    user_id: UUID
    title: str | None = None
    sections: list[APASection] | None = None
    presentation: PresentationInfo | None = None
    docx_bytes: bytes | None = None


@dataclass(frozen=True)
class AugmentDocumentInput:
    document_id: UUID
    user_id: UUID
    sources: list[str]
    additional_notes: str | None = None


@dataclass(frozen=True)
class ExportDocumentInput:
    document_id: UUID
    user_id: UUID
    export: str


@dataclass(frozen=True)
class DocumentStatusOutput:
    document_id: UUID
    status: DocumentStatus
    error_message: str | None = None


@dataclass(frozen=True)
class DocumentDetailOutput:
    document_id: UUID
    title: str
    status: DocumentStatus
    export_url: str | None
    sections: list[APASection]
    sources: list[SourceReference]


@dataclass(frozen=True)
class DocumentReference:
    id: UUID
    title: str
    updated_at: datetime
