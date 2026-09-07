from __future__ import annotations

import asyncio
import dataclasses
import json
from dataclasses import replace
from datetime import datetime
from enum import Enum
from uuid import UUID

from application.dtos.document_dtos import DocumentReference
from application.dtos.export_result import ExportResult
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.source_repository_port import SourceRepositoryPort
from domain.entities.document import Document, DocumentStatus
from domain.value_objects.apa_structure import (
    APA7_DOCUMENT_STYLES,
    APASection,
    APASectionType,
)
from domain.value_objects.document_node import DocumentNode
from domain.value_objects.document_type import DocumentType
from domain.value_objects.source_ref import SourceReference
from supabase import Client


class SupabaseDocumentRepository(DocumentRepositoryPort):
    _TABLE = "documents"

    def __init__(
        self, client: Client, source_repository: SourceRepositoryPort
    ) -> None:
        self._client = client
        self._sources = source_repository

    async def save(self, document: Document) -> None:
        await asyncio.to_thread(self._save_sync, document)

    async def get_by_id(self, document_id: UUID) -> Document | None:
        row = await asyncio.to_thread(self._get_row_sync, str(document_id))
        if row is None:
            return None
        return await self._to_entity(row)

    async def list_by_user(self, user_id: UUID) -> list[DocumentReference]:
        rows = await asyncio.to_thread(
            self._list_rows_by_user_sync, str(user_id)
        )
        return [await self._to_document_reference(row) for row in rows]

    async def delete(self, document_id: UUID) -> None:
        await asyncio.to_thread(self._delete_sync, str(document_id))

    async def save_export_result(
        self, document_id: UUID, export_result: ExportResult
    ) -> None:
        await asyncio.to_thread(
            self._update_fields_sync,
            str(document_id),
            {"document_url": export_result.url},
        )

    async def get_export_result(
        self, document_id: UUID
    ) -> ExportResult | None:
        row = await asyncio.to_thread(self._get_row_sync, str(document_id))
        if row is None or not row.get("document_url"):
            return None
        return ExportResult(url=row["document_url"])

    def _save_sync(self, document: Document) -> None:
        self._client.table(self._TABLE).upsert(
            self._to_row(document)
        ).execute()

    def _get_row_sync(self, document_id: str) -> dict | None:
        result = (
            self._client.table(self._TABLE)
            .select("*")
            .eq("id", document_id)
            .maybe_single()
            .execute()
        )
        return result.data if result and result.data else None

    def _list_rows_by_user_sync(self, user_id: str) -> list[dict]:
        result = (
            self._client.table(self._TABLE)
            .select("id, title, updated_at")
            .eq("user_id", user_id)
            .eq("status", "done")
            .order("updated_at", desc=True)
            .execute()
        )
        return result.data or []

    def _delete_sync(self, document_id: str) -> None:
        self._client.table(self._TABLE).delete().eq(
            "id", document_id
        ).execute()

    def _update_fields_sync(self, document_id: str, fields: dict) -> None:
        self._client.table(self._TABLE).update(fields).eq(
            "id", document_id
        ).execute()

    def _to_row(self, document: Document) -> dict:
        return {
            "id": str(document.id),
            "user_id": str(document.user_id),
            "title": document.title,
            "document_type": document.document_type.value,
            "source_ids": [str(s.id) for s in document.raw_sources],
            "status": document.status.value,
            "node_tree": document.to_node_tree(),
            "sources": [_to_jsonable(s) for s in document.sources],
            "created_at": document.created_at.isoformat(),
            "updated_at": document.updated_at.isoformat(),
            "error_message": document.error_message,
            "error_stage": document.error_stage,
        }

    async def _to_entity(self, row: dict) -> Document:
        raw_sources = []
        for sid in row.get("source_ids") or []:
            source = await self._sources.get_by_id(UUID(sid))
            if source is None:
                raise ValueError(
                    f"Document '{row['id']}' references a missing source "
                    f"'{sid}'."
                )
            raw_sources.append(source)

        sections, global_style = _document_data_from_row(row)
        return Document(
            id=UUID(row["id"]),
            user_id=UUID(row["user_id"]),
            title=row["title"],
            document_type=DocumentType(row["document_type"]),
            raw_sources=raw_sources,
            status=DocumentStatus(row["status"]),
            sections=sections,
            sources=[SourceReference(**s) for s in row["sources"]],
            global_style=global_style,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_message=row.get("error_message"),
            error_stage=row.get("error_stage"),
        )

    async def _to_document_reference(self, row: dict) -> DocumentReference:
        return DocumentReference(
            id=UUID(row["id"]),
            title=row["title"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


def _to_jsonable(value) -> dict:
    data = dataclasses.asdict(value)
    return json.loads(json.dumps(data, default=_json_default))


def _json_default(obj):
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _section_to_dict(section: APASection) -> dict:
    return {
        "section_type": section.section_type.value,
        "heading": section.heading.to_dict(),
        "body_nodes": [n.to_dict() for n in section.body_nodes],
    }


def _section_from_dict(data: dict) -> APASection:
    return APASection(
        section_type=APASectionType(data["section_type"]),
        heading=DocumentNode.from_dict(data["heading"]),
        body_nodes=tuple(
            DocumentNode.from_dict(n) for n in data["body_nodes"]
        ),
    )


def _document_data_from_row(
    row: dict,
) -> tuple[list[APASection], dict]:
    """Read the canonical root tree and the two legacy persistence shapes."""
    node_tree = row.get("node_tree")
    if isinstance(node_tree, dict):
        children = node_tree.get("children") or []
        sections = _sections_from_children(children)
        global_style = (
            node_tree.get("global_style")
            or node_tree.get("document_style")
            or node_tree.get("document_styles")
            or {}
        )
        return sections, {
            **APA7_DOCUMENT_STYLES,
            **global_style,
        }

    legacy_sections = node_tree
    if not isinstance(legacy_sections, list):
        legacy_sections = row.get("sections") or []
    global_style = (
        row.get("document_style") or row.get("document_styles") or {}
    )
    return [_section_from_dict(section) for section in legacy_sections], {
        **APA7_DOCUMENT_STYLES,
        **global_style,
    }


def _sections_from_children(children: list) -> list[APASection]:
    if not isinstance(children, list):
        raise ValueError("node_tree.children must be a JSON array.")

    grouped: dict[APASectionType, list[DocumentNode]] = {}
    current_section: APASectionType | None = None
    canonical_sections = list(APASectionType)
    next_section_index = 0
    for raw_node in children:
        node = DocumentNode.from_dict(raw_node)
        if node.type == "heading-1":
            if node.section_type is not None:
                current_section = APASectionType(node.section_type)
                next_section_index = (
                    canonical_sections.index(current_section) + 1
                )
            else:
                if next_section_index >= len(canonical_sections):
                    raise ValueError(
                        "The document has more root heading-1 nodes than "
                        "canonical APA sections."
                    )
                current_section = canonical_sections[next_section_index]
                next_section_index += 1
            if current_section in grouped:
                raise ValueError(
                    f"Section '{current_section.value}' has more than one "
                    "root heading-1."
                )
        elif node.section_type is not None:
            declared_section = APASectionType(node.section_type)
            if current_section is not declared_section:
                raise ValueError(
                    f"Node declares section '{declared_section.value}' "
                    "before its heading-1."
                )

        if current_section is None:
            raise ValueError(
                "Root content must start with a heading-1 that defines or "
                "identifies its section."
            )
        if node.section_type is None:
            node = replace(node, section_type=current_section.value)
        grouped.setdefault(current_section, []).append(node)

    sections: list[APASection] = []
    for section_type, nodes in grouped.items():
        heading = nodes[0] if nodes else None
        if heading is None or heading.type != "heading-1":
            raise ValueError(
                f"Section '{section_type.value}' must start with heading-1."
            )
        sections.append(
            APASection(
                section_type=section_type,
                heading=heading,
                body_nodes=tuple(nodes[1:]),
            )
        )
    sections.sort(key=lambda section: section.section_type.order)
    return sections
