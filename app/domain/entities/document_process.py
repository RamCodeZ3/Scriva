from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from domain.exceptions import DocumentProcessTransitionError


class DocumentProcessType(Enum):
    GENERATION = "generation"
    EXPANSION = "expansion"


class DocumentProcessStatus(Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    GENERATING = "generating"
    EXPANDING = "expanding"
    DRAFTING = "drafting"
    DONE = "done"
    FAILED = "failed"


class DocumentProcessErrorStage(Enum):
    SOURCE_EXTRACTION = "source_extraction"
    AI_GENERATION = "ai_generation"
    AI_EXPANSION = "ai_expansion"
    DOCUMENT_DRAFTING = "document_drafting"
    DOCUMENT_EXPORT = "document_export"
    INTERNAL = "internal"


_TRANSITIONS = {
    DocumentProcessStatus.PENDING: {DocumentProcessStatus.EXTRACTING},
    DocumentProcessStatus.EXTRACTING: {
        DocumentProcessStatus.GENERATING,
        DocumentProcessStatus.EXPANDING,
    },
    DocumentProcessStatus.GENERATING: {DocumentProcessStatus.DRAFTING},
    DocumentProcessStatus.EXPANDING: {DocumentProcessStatus.DRAFTING},
    DocumentProcessStatus.DRAFTING: {DocumentProcessStatus.DONE},
}


@dataclass
class DocumentProcess:
    id: UUID
    document_id: UUID
    process_type: DocumentProcessType
    status: DocumentProcessStatus
    source_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
    error_stage: DocumentProcessErrorStage | None = None
    error_message: str | None = None
    ai_provider: str | None = None
    ai_model_used: str | None = None
    ai_attempts: list[dict] = field(default_factory=list)

    @classmethod
    def create_generation(
        cls, document_id: UUID, source_ids: list[UUID]
    ) -> DocumentProcess:
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            document_id=document_id,
            process_type=DocumentProcessType.GENERATION,
            status=DocumentProcessStatus.PENDING,
            source_ids=list(source_ids),
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_expansion(
        cls, document_id: UUID, source_ids: list[UUID]
    ) -> DocumentProcess:
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            document_id=document_id,
            process_type=DocumentProcessType.EXPANSION,
            status=DocumentProcessStatus.EXTRACTING,
            source_ids=list(source_ids),
            created_at=now,
            updated_at=now,
        )

    def transition_to(self, status: DocumentProcessStatus) -> None:
        allowed = _TRANSITIONS.get(self.status, set())
        if status not in allowed:
            raise DocumentProcessTransitionError(
                f"Invalid document process transition from "
                f"'{self.status.value}' to '{status.value}'."
            )
        if (
            self.process_type is DocumentProcessType.GENERATION
            and status is DocumentProcessStatus.EXPANDING
        ) or (
            self.process_type is DocumentProcessType.EXPANSION
            and status is DocumentProcessStatus.GENERATING
        ):
            raise DocumentProcessTransitionError(
                f"Process type '{self.process_type.value}' cannot enter "
                f"'{status.value}'."
            )
        self.status = status
        self.error_stage = None
        self.error_message = None
        self._touch()

    def fail(self, message: str, stage: DocumentProcessErrorStage) -> None:
        if self.status in {
            DocumentProcessStatus.DONE,
            DocumentProcessStatus.FAILED,
        }:
            raise DocumentProcessTransitionError(
                f"Cannot fail a process in '{self.status.value}' status."
            )
        self.status = DocumentProcessStatus.FAILED
        self.error_stage = stage
        self.error_message = message
        self._touch()

    def record_ai_metadata(
        self,
        provider: str | None,
        model: str | None,
        attempts: list[dict],
    ) -> None:
        self.ai_provider = provider
        self.ai_model_used = model
        self.ai_attempts = list(attempts)
        self._touch()

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)
