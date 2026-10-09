import asyncio
from uuid import UUID

from domain.entities.document import Document
from domain.entities.document_process import (
    DocumentProcess,
    DocumentProcessErrorStage,
    DocumentProcessStatus,
)
from domain.entities.source import Source, SourceType
from domain.value_objects.presentation_info import PresentationInfo

from application.dtos.document_dtos import (
    DocumentProgressCallback,
    document_to_output,
)
from application.exceptions import (
    AIProvidersExhaustedError,
    DocumentNotFoundError,
    NoSourcesExtractedError,
    SourceNotFoundError,
)
from application.ports.document_process_repository_port import (
    DocumentProcessRepositoryPort,
)
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.document_writer_port import DocumentWriterPort
from application.ports.extractor_factory_port import ExtractorFactoryPort
from application.ports.source_extractor_port import ExtractedSource
from application.ports.source_repository_port import SourceRepositoryPort


class ProcessDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepositoryPort,
        process_repository: DocumentProcessRepositoryPort,
        source_repository: SourceRepositoryPort,
        extractor_factory: ExtractorFactoryPort,
        document_writer: DocumentWriterPort,
    ) -> None:
        self._documents = document_repository
        self._processes = process_repository
        self._sources = source_repository
        self._extractor_factory = extractor_factory
        self._writer = document_writer

    async def execute(
        self,
        document_id: UUID,
        presentation: PresentationInfo,
        additional_notes: str | None = None,
        on_progress: DocumentProgressCallback | None = None,
    ) -> None:
        document = await self._documents.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError(
                f"Document '{document_id}' does not exist."
            )
        process = await self._processes.get_latest(document.id)
        if process is None:
            raise DocumentNotFoundError(
                f"Document '{document_id}' has no generation process."
            )

        sources: list[Source] = []
        for raw_source in document.raw_sources:
            source = await self._sources.get_by_id(raw_source.id)
            if source is None:
                raise SourceNotFoundError(
                    f"Source '{raw_source.id}' does not exist."
                )
            sources.append(source)

        error_stage = "source_extraction"
        try:
            document.start_extraction()
            await self._save_state(
                document, process, DocumentProcessStatus.EXTRACTING
            )
            await self._report(document, on_progress)

            extracted_sources = await self._extract_sources(sources)

            if not extracted_sources:
                raise NoSourcesExtractedError(
                    "None of the provided sources could be extracted."
                )
            if len(extracted_sources) < document.blueprint.min_sources:
                raise NoSourcesExtractedError(
                    f"A '{document.document_type.value}' document needs at "
                    f"least {document.blueprint.min_sources} successfully "
                    "extracted sources."
                )

            combined_content = "\n\n".join(
                f"[Source id: {s.id}; kind: {s.source_type.value}]\n"
                f"{s.get_content()}"
                for i, s in enumerate(extracted_sources)
            )

            document.start_generation()
            await self._save_state(
                document, process, DocumentProcessStatus.GENERATING
            )
            await self._report(document, on_progress)

            error_stage = "ai_generation"
            writer_result = await self._writer.write(
                source_content=combined_content,
                sources=extracted_sources,
                title=document.title,
                document_type=document.document_type,
                presentation=presentation,
                additional_notes=additional_notes,
            )
            process.record_ai_metadata(
                writer_result.metadata.provider,
                writer_result.metadata.model,
                [
                    _attempt_to_dict(item)
                    for item in writer_result.metadata.attempts
                ],
            )
            await self._processes.save(process)
            error_stage = "document_drafting"
            document.start_drafting()
            await self._save_state(
                document, process, DocumentProcessStatus.DRAFTING
            )
            await self._report(document, on_progress)
            document.complete(
                title=writer_result.title,
                sections=writer_result.sections,
                sources=writer_result.references,
                global_style={
                    **document.global_style,
                    **writer_result.global_style,
                },
            )
            await self._documents.save(document)

        except asyncio.CancelledError:
            document.fail(
                "The document process was interrupted before completion.",
                "internal",
            )
            if process.status not in {
                DocumentProcessStatus.DONE,
                DocumentProcessStatus.FAILED,
            }:
                process.fail(
                    "The document process was interrupted before completion.",
                    DocumentProcessErrorStage.INTERNAL,
                )
            await asyncio.shield(self._documents.save(document))
            await asyncio.shield(self._processes.save(process))
            await self._report(document, on_progress)
            raise
        except Exception as exc:
            document.fail(str(exc), error_stage)
            await self._documents.save(document)
            if isinstance(exc, AIProvidersExhaustedError):
                process.record_ai_metadata(
                    None,
                    None,
                    [_attempt_to_dict(item) for item in exc.attempts],
                )
            if process.status not in {
                DocumentProcessStatus.DONE,
                DocumentProcessStatus.FAILED,
            }:
                process.fail(str(exc), _error_stage(error_stage))
                await self._processes.save(process)
            await self._report(document, on_progress)
            raise

    async def _save_state(
        self,
        document: Document,
        process: DocumentProcess,
        status: DocumentProcessStatus,
    ) -> None:
        process.transition_to(status)
        await self._documents.save(document)
        await self._processes.save(process)

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
                extracted_result = await extractor.extract_with_metadata(
                    source.raw
                )
                if not isinstance(extracted_result, ExtractedSource):
                    extracted_result = ExtractedSource(
                        content=await extractor.extract(source.raw)
                    )
                source.mark_extracted(
                    extracted_result.content,
                    title=extracted_result.title,
                    author=extracted_result.author,
                    published_at=extracted_result.published_at,
                    site_name=extracted_result.site_name,
                    canonical_url=extracted_result.canonical_url
                    or (
                        source.raw
                        if source.source_type
                        in {SourceType.WEB, SourceType.YOUTUBE}
                        else None
                    ),
                )
                extracted.append(source)
            except Exception as exc:
                source.mark_failed(str(exc))
            finally:
                await self._sources.save(source)
        return extracted


def _attempt_to_dict(attempt) -> dict:
    return {
        "provider": attempt.provider,
        "model": attempt.model,
        "outcome": attempt.outcome,
        "error_kind": attempt.error_kind,
        "error_detail": attempt.error_detail,
        "latency_ms": attempt.latency_ms,
    }


def _error_stage(value: str) -> DocumentProcessErrorStage:
    try:
        return DocumentProcessErrorStage(value)
    except ValueError:
        return DocumentProcessErrorStage.INTERNAL
