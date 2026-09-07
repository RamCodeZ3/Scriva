from __future__ import annotations

from domain.entities.document import Document, DocumentStatus
from domain.entities.source import Source
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import APASectionType

from application.dtos.document_dtos import (
    AugmentDocumentInput,
    DocumentFileOutput,
    DocumentProgressCallback,
    document_to_output,
)
from application.exceptions import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    NoSourcesExtractedError,
)
from application.ports.document_exporter_port import DocumentExporterPort
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.document_writer_port import DocumentWriterPort
from application.ports.docx_cache_port import DocxCachePort
from application.ports.extractor_factory_port import ExtractorFactoryPort
from application.ports.source_repository_port import SourceRepositoryPort
from application.services.document_docx_cache import cache_docx


class AugmentDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepositoryPort,
        source_repository: SourceRepositoryPort,
        extractor_factory: ExtractorFactoryPort,
        document_writer: DocumentWriterPort,
        exporter: DocumentExporterPort,
        cache: DocxCachePort,
    ) -> None:
        self._documents = document_repository
        self._sources = source_repository
        self._extractor_factory = extractor_factory
        self._writer = document_writer
        self._exporter = exporter
        self._cache = cache

    async def execute(
        self,
        data: AugmentDocumentInput,
        on_progress: DocumentProgressCallback | None = None,
    ) -> DocumentFileOutput:
        document = await self._documents.get_by_id(data.document_id)
        if document is None:
            raise DocumentNotFoundError(
                f"Document '{data.document_id}' does not exist."
            )
        if document.user_id != data.user_id:
            raise DocumentAccessDeniedError(
                f"Document '{data.document_id}' does not belong to this "
                "account."
            )
        if document.status != DocumentStatus.DONE:
            raise DocumentBuildError(
                "Cannot add info to a document in "
                f"'{document.status.value}' status; "
                "it must be 'done'."
            )

        new_sources = [
            Source.create_auto(raw, data.user_id) for raw in data.sources
        ]
        error_stage = "source_extraction"
        try:
            for source in new_sources:
                await self._sources.save(source)
            document.start_augmentation(new_sources)
            await self._documents.save(document)
            await self._report(document, on_progress)

            extracted_sources = await self._extract_sources(new_sources)
            if not extracted_sources:
                raise NoSourcesExtractedError(
                    "None of the new sources could be extracted; "
                    "nothing was added to the document."
                )

            document.start_expansion()
            await self._documents.save(document)
            await self._report(document, on_progress)

            new_content = "\n\n".join(
                f"[Fuente nueva {i + 1}]\n{s.get_content()}"
                for i, s in enumerate(extracted_sources)
            )
            error_stage = "ai_expansion"
            (
                title,
                sections,
                references,
                global_style,
            ) = await self._writer.augment(
                existing_sections=document.sections,
                existing_references=document.sources,
                new_content=new_content,
                document_type=document.document_type,
                existing_global_style=document.global_style,
                additional_notes=data.additional_notes,
            )

            error_stage = "document_drafting"
            original_cover = document.get_section(APASectionType.PRESENTATION)
            if original_cover is not None:
                sections = [original_cover] + [
                    section
                    for section in sections
                    if section.section_type is not APASectionType.PRESENTATION
                ]

            document.start_drafting()
            await self._documents.save(document)
            await self._report(document, on_progress)
            document.augment(
                title=title,
                sections=sections,
                sources=references,
                new_raw_sources=new_sources,
            )
            document.update_content(
                global_style={**document.global_style, **global_style}
            )
            await self._documents.save(document)
        except Exception as exc:
            document.fail(str(exc), error_stage)
            await self._documents.save(document)
            await self._report(document, on_progress)
            raise

        try:
            metadata = document_to_output(document)
            exported = await self._exporter.export(document)
            if exported.file_bytes is None:
                raise RuntimeError(
                    "The DOCX exporter returned no binary content."
                )
            await cache_docx(
                self._cache,
                document,
                exported.file_bytes,
                invalidate_existing=True,
            )
            await self._report(document, on_progress)
        except Exception as exc:
            document.fail(str(exc), "document_export")
            await self._documents.save(document)
            await self._report(document, on_progress)
            raise
        return DocumentFileOutput(
            document=metadata,
            file_bytes=exported.file_bytes,
            file_name=exported.file_name or f"{document.id}.docx",
            content_type=exported.content_type or "application/octet-stream",
        )

    @staticmethod
    async def _report(
        document: Document,
        on_progress: DocumentProgressCallback | None,
    ) -> None:
        if on_progress is not None:
            await on_progress(document_to_output(document))

    async def _extract_sources(self, sources: list[Source]) -> list[Source]:
        extracted: list[Source] = []
        for source in sources:
            try:
                extractor = self._extractor_factory.get_extractor(
                    source.source_type
                )
                content = await extractor.extract(source.raw)
                source.mark_extracted(content)
                extracted.append(source)
            except Exception as exc:
                source.mark_failed(str(exc))
            finally:
                await self._sources.save(source)
        return extracted
