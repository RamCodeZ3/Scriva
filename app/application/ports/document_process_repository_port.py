from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from uuid import UUID

from domain.entities.document import Document
from domain.entities.document_process import DocumentProcess


class DocumentProcessRepositoryPort(ABC):
    @abstractmethod
    async def create(self, process: DocumentProcess) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_document_with_process(
        self, document: Document, process: DocumentProcess
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_latest(self, document_id: UUID) -> DocumentProcess | None:
        raise NotImplementedError

    @abstractmethod
    async def get_latest_many(
        self, document_ids: list[UUID]
    ) -> dict[UUID, DocumentProcess]:
        raise NotImplementedError

    @abstractmethod
    async def save(self, process: DocumentProcess) -> None:
        raise NotImplementedError

    @abstractmethod
    async def fail_stale(self, max_age: timedelta) -> int:
        raise NotImplementedError
