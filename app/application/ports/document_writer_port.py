from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from domain.value_objects.apa_structure import APASection
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from domain.value_objects.source_ref import SourceReference


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
    ) -> tuple[str, list[APASection], list[SourceReference], dict[str, Any]]:
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
    ) -> tuple[str, list[APASection], list[SourceReference], dict[str, Any]]:
        """
        Merges `new_content` into an existing document's sections.
        Implementations should avoid re-emitting sections the new
        content doesn't affect, to keep output tokens down.
        """
        raise NotImplementedError
