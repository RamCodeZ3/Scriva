from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from application.ports.source_repository_port import SourceRepositoryPort
from domain.entities.source import FileKind, Source, SourceStatus, SourceType
from supabase import Client


class SupabaseSourceRepository(SourceRepositoryPort):
    _TABLE = "sources"

    def __init__(self, client: Client) -> None:
        self._client = client

    async def save(self, source: Source) -> None:
        await asyncio.to_thread(self._save_sync, source)

    async def get_by_id(self, source_id: UUID) -> Source | None:
        return await asyncio.to_thread(self._get_by_id_sync, source_id)

    async def list_by_user(self, user_id: UUID) -> list[Source]:
        return await asyncio.to_thread(self._list_by_user_sync, user_id)

    async def get_by_id_for_user(
        self, source_id: UUID, user_id: UUID
    ) -> Source | None:
        return await asyncio.to_thread(
            self._get_by_id_for_user_sync, source_id, user_id
        )

    def _save_sync(self, source: Source) -> None:
        self._client.table(self._TABLE).upsert(self._to_row(source)).execute()

    def _get_by_id_sync(self, source_id: UUID) -> Source | None:
        result = (
            self._client.table(self._TABLE)
            .select("*")
            .eq("id", str(source_id))
            .maybe_single()
            .execute()
        )
        return self._to_entity(result.data) if result and result.data else None

    def _list_by_user_sync(self, user_id: UUID) -> list[Source]:
        result = (
            self._client.table(self._TABLE)
            .select("*")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .execute()
        )
        return [self._to_entity(row) for row in result.data or []]

    def _get_by_id_for_user_sync(
        self, source_id: UUID, user_id: UUID
    ) -> Source | None:
        result = (
            self._client.table(self._TABLE)
            .select("*")
            .eq("id", str(source_id))
            .eq("user_id", str(user_id))
            .maybe_single()
            .execute()
        )
        return self._to_entity(result.data) if result and result.data else None

    @staticmethod
    def _to_row(source: Source) -> dict:
        return {
            "id": str(source.id),
            "user_id": str(source.user_id) if source.user_id else None,
            "type": source.source_type.value,
            "raw": source.raw,
            "status": source.status.value,
            "file_kind": source.file_kind.value if source.file_kind else None,
            "content": source.content,
            "char_count": source.char_count,
            "error_message": source.error_message,
            "metadata": {
                "title": source.title,
                "author": source.author,
                "published_at": source.published_at.isoformat()
                if source.published_at
                else None,
                "site_name": source.site_name,
                "canonical_url": source.canonical_url,
                "label": source.label,
            },
        }

    @staticmethod
    def _to_entity(row: dict) -> Source:
        metadata = row.get("metadata") or {}
        return Source(
            id=UUID(row["id"]),
            source_type=SourceType(row["type"]),
            raw=row["raw"],
            status=SourceStatus(row["status"]),
            user_id=UUID(row["user_id"]) if row.get("user_id") else None,
            file_kind=FileKind(row["file_kind"])
            if row.get("file_kind")
            else None,
            content=row.get("content"),
            char_count=row.get("char_count"),
            error_message=row.get("error_message"),
            created_at=(
                datetime.fromisoformat(row["created_at"])
                if row.get("created_at")
                else None
            ),
            title=metadata.get("title"),
            author=metadata.get("author"),
            published_at=(
                datetime.fromisoformat(metadata["published_at"])
                if metadata.get("published_at")
                else None
            ),
            site_name=metadata.get("site_name"),
            canonical_url=metadata.get("canonical_url"),
            label=metadata.get("label"),
        )
