from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

from application.ports.document_process_repository_port import (
    DocumentProcessRepositoryPort,
)
from domain.entities.document import Document
from domain.entities.document_process import (
    DocumentProcess,
    DocumentProcessErrorStage,
    DocumentProcessStatus,
    DocumentProcessType,
)
from domain.exceptions import ActiveDocumentProcessError

from supabase import Client


class SupabaseDocumentProcessRepository(DocumentProcessRepositoryPort):
    _TABLE = "document_process_details"
    _CURRENT_VIEW = "document_current_process"

    def __init__(self, client: Client) -> None:
        self._client = client

    async def create(self, process: DocumentProcess) -> None:
        await asyncio.to_thread(self._create_sync, process)

    async def create_document_with_process(
        self, document: Document, process: DocumentProcess
    ) -> None:
        await asyncio.to_thread(
            self._create_document_with_process_sync, document, process
        )

    async def get_latest(self, document_id: UUID) -> DocumentProcess | None:
        row = await asyncio.to_thread(self._get_latest_sync, document_id)
        return _to_entity(row) if row else None

    async def get_latest_many(
        self, document_ids: list[UUID]
    ) -> dict[UUID, DocumentProcess]:
        if not document_ids:
            return {}
        rows = await asyncio.to_thread(
            self._get_latest_many_sync, document_ids
        )
        processes = (_to_entity(row) for row in rows)
        return {process.document_id: process for process in processes}

    async def save(self, process: DocumentProcess) -> None:
        await asyncio.to_thread(self._save_sync, process)

    async def fail_stale(self, max_age: timedelta) -> int:
        return await asyncio.to_thread(self._fail_stale_sync, max_age)

    def _create_sync(self, process: DocumentProcess) -> None:
        try:
            self._client.table(self._TABLE).insert(_to_row(process)).execute()
        except Exception as exc:
            _raise_process_conflict(exc)
            raise

    def _create_document_with_process_sync(
        self, document: Document, process: DocumentProcess
    ) -> None:
        params = {
            "p_document_id": str(document.id),
            "p_user_id": str(document.user_id),
            "p_title": document.title,
            "p_document_type": document.document_type.value,
            "p_sources": [],
            "p_source_ids": [
                str(source_id) for source_id in process.source_ids
            ],
        }
        try:
            self._client.rpc("create_document_with_process", params).execute()
        except Exception as exc:
            _raise_process_conflict(exc)
            raise

    def _get_latest_sync(self, document_id: UUID) -> dict | None:
        result = (
            self._client.table(self._CURRENT_VIEW)
            .select("*")
            .eq("document_id", str(document_id))
            .maybe_single()
            .execute()
        )
        return result.data if result and result.data else None

    def _get_latest_many_sync(self, document_ids: list[UUID]) -> list[dict]:
        result = (
            self._client.table(self._CURRENT_VIEW)
            .select("*")
            .in_("document_id", [str(value) for value in document_ids])
            .execute()
        )
        return result.data or []

    def _save_sync(self, process: DocumentProcess) -> None:
        row = _to_row(process)
        row.pop("id")
        row.pop("document_id")
        row.pop("created_at")
        self._client.table(self._TABLE).update(row).eq(
            "id", str(process.id)
        ).execute()

    def _fail_stale_sync(self, max_age: timedelta) -> int:
        seconds = max(1, int(max_age.total_seconds()))
        result = self._client.rpc(
            "fail_stale_document_processes",
            {"p_max_age": f"{seconds} seconds"},
        ).execute()
        return int(result.data or 0)


def _to_row(process: DocumentProcess) -> dict:
    return {
        "id": str(process.id),
        "document_id": str(process.document_id),
        "process_type": process.process_type.value,
        "status": process.status.value,
        "error_stage": (
            process.error_stage.value if process.error_stage else None
        ),
        "error_message": process.error_message,
        "source_ids": [str(value) for value in process.source_ids],
        "ai_provider": process.ai_provider,
        "ai_model_used": process.ai_model_used,
        "ai_attempts": process.ai_attempts,
        "created_at": process.created_at.isoformat(),
        "updated_at": process.updated_at.isoformat(),
    }


def _to_entity(row: dict) -> DocumentProcess:
    error_stage = row.get("error_stage")
    return DocumentProcess(
        id=UUID(row["id"]),
        document_id=UUID(row["document_id"]),
        process_type=DocumentProcessType(row["process_type"]),
        status=DocumentProcessStatus(row["status"]),
        error_stage=(
            DocumentProcessErrorStage(error_stage) if error_stage else None
        ),
        error_message=row.get("error_message"),
        source_ids=[UUID(value) for value in row.get("source_ids") or []],
        ai_provider=row.get("ai_provider"),
        ai_model_used=row.get("ai_model_used"),
        ai_attempts=list(row.get("ai_attempts") or []),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _raise_process_conflict(exc: Exception) -> None:
    code = getattr(exc, "code", None)
    if code == "23505" or "23505" in str(exc):
        raise ActiveDocumentProcessError(
            "The document already has an active process."
        ) from exc
