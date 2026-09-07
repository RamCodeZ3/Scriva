from uuid import UUID

from application.dtos.document_dtos import (
    DocumentFileOutput,
    DocumentOutput,
    build_source_errors,
)
from application.exceptions import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
)
from application.ports.document_exporter_port import DocumentExporterPort
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.docx_cache_port import DocxCachePort
from application.services.document_docx_cache import (
    cache_docx,
    get_cached_docx,
)


class GetDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepositoryPort,
        exporter: DocumentExporterPort,
        cache: DocxCachePort,
    ) -> None:
        self._documents = document_repository
        self._exporter = exporter
        self._cache = cache

    async def execute(
        self, document_id: UUID, user_id: UUID
    ) -> DocumentFileOutput:
        document = await self._documents.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError(
                f"Document '{document_id}' does not exist."
            )
        if document.user_id != user_id:
            raise DocumentAccessDeniedError(
                f"Document '{document_id}' does not belong to this account."
            )

        metadata = DocumentOutput(
            id=document.id,
            title=document.title,
            document_type=document.document_type,
            status=document.status,
            sections=document.sections,
            user_id=document.user_id,
            error_message=document.error_message,
            source_ids=[s.id for s in document.raw_sources],
            source_errors=build_source_errors(document.raw_sources),
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
        docx_bytes = await get_cached_docx(self._cache, document)
        file_name = f"{document.id}.docx"
        content_type = (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
        if docx_bytes is None:
            exported = await self._exporter.export(document)
            if exported.file_bytes is None:
                raise RuntimeError(
                    "The DOCX exporter returned no binary content."
                )
            docx_bytes = exported.file_bytes
            file_name = exported.file_name or file_name
            content_type = exported.content_type or content_type
            await cache_docx(self._cache, document, docx_bytes)
        return DocumentFileOutput(
            document=metadata,
            file_bytes=docx_bytes,
            file_name=file_name,
            content_type=content_type,
        )
