from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from domain.entities.source import Source
from domain.value_objects.apa_structure import APASection
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from domain.value_objects.source_ref import SourceReference


@dataclass(frozen=True)
class AIAttempt:
    provider: str
    model: str
    outcome: str
    error_kind: str | None = None
    error_detail: str | None = None
    latency_ms: int = 0


@dataclass(frozen=True)
class AIWriterMetadata:
    provider: str | None
    model: str | None
    attempts: tuple[AIAttempt, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DocumentWriterResult:
    title: str
    sections: list[APASection]
    references: list[SourceReference]
    global_style: dict[str, Any]
    metadata: AIWriterMetadata


class DocumentWriterPort(ABC):
    @abstractmethod
    async def write(
        self,
        *,
        source_content: str,
        title: str,
        document_type: DocumentType,
        presentation: PresentationInfo,
        additional_notes: str | None = None,
        sources: list[Source] | None = None,
    ) -> DocumentWriterResult:
        raise NotImplementedError

    @abstractmethod
    async def augment(
        self,
        *,
        existing_sections: list[APASection],
        existing_references: list[SourceReference],
        new_content: str,
        document_type: DocumentType,
        existing_global_style: dict[str, Any],
        additional_notes: str | None = None,
        sources: list[Source] | None = None,
    ) -> DocumentWriterResult:
        """
        Merges `new_content` into an existing document's sections.
        Implementations should avoid re-emitting sections the new
        content doesn't affect, to keep output tokens down.
        """
        raise NotImplementedError
