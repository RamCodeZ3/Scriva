from domain.entities.document import Document, DocumentStatus
from domain.entities.source import Source
from domain.exceptions import DocumentBuildError

from application.dtos.document_dtos import (
    CreateDocumentInput,
    DocumentFileOutput,
    DocumentProgressCallback,
    document_to_output,
)
from application.exceptions import UserNotFoundError
from application.ports.document_exporter_port import DocumentExporterPort
from application.ports.document_job_dispatcher_port import (
    DocumentJobDispatcherPort,
)
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.docx_cache_port import DocxCachePort
from application.ports.source_repository_port import SourceRepositoryPort
from application.ports.user_repository_port import UserRepositoryPort
from application.services.document_docx_cache import cache_docx


class CreateDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepositoryPort,
        source_repository: SourceRepositoryPort,
        user_repository: UserRepositoryPort,
        job_dispatcher: DocumentJobDispatcherPort,
        exporter: DocumentExporterPort,
        cache: DocxCachePort,
    ) -> None:
        self._documents = document_repository
        self._sources = source_repository
        self._users = user_repository
        self._dispatcher = job_dispatcher
        self._exporter = exporter
        self._cache = cache

    async def execute(
        self,
        data: CreateDocumentInput,
        on_progress: DocumentProgressCallback | None = None,
    ) -> DocumentFileOutput:
        user = await self._users.get_by_id(data.user_id)
        if user is None:
            raise UserNotFoundError(f"User '{data.user_id}' does not exist.")

        raw_sources = [
            Source.create_auto(raw, data.user_id) for raw in data.sources
        ]
        for source in raw_sources:
            await self._sources.save(source)

        document = Document.create(
            user_id=data.user_id,
            title=data.title,
            document_type=data.document_type,
            raw_sources=raw_sources,
        )
        await self._documents.save(document)

        try:
            await self._dispatcher.dispatch(
                document.id,
                data.presentation,
                data.additional_notes,
                on_progress,
            )
        except Exception:
            pass

        final_document = (
            await self._documents.get_by_id(document.id) or document
        )
        if final_document.status == DocumentStatus.FAILED:
            raise DocumentBuildError(
                final_document.error_message or "Document generation failed."
            )

        try:
            metadata = document_to_output(final_document)
            exported = await self._exporter.export(final_document)
            if exported.file_bytes is None:
                raise RuntimeError(
                    "The DOCX exporter returned no binary content."
                )
            await cache_docx(
                self._cache,
                final_document,
                exported.file_bytes,
                invalidate_existing=True,
            )
            if on_progress is not None:
                await on_progress(metadata)
        except Exception as exc:
            final_document.fail(str(exc), "document_export")
            await self._documents.save(final_document)
            if on_progress is not None:
                await on_progress(document_to_output(final_document))
            raise
        return DocumentFileOutput(
            document=metadata,
            file_bytes=exported.file_bytes,
            file_name=exported.file_name or f"{final_document.id}.docx",
            content_type=exported.content_type or "application/octet-stream",
        )
