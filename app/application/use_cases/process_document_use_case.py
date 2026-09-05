from uuid import UUID

from domain.entities.document import Document
from domain.entities.source import Source

from application.dtos.document_dtos import (
    DocumentProgressCallback,
    document_to_output,
)
from application.exceptions import (
    DocumentNotFoundError,
    NoSourcesExtractedError,
    SourceNotFoundError,
)
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.document_writer_port import DocumentWriterPort
from application.ports.extractor_factory_port import ExtractorFactoryPort
from application.ports.source_repository_port import SourceRepositoryPort


class ProcessDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepositoryPort,
        source_repository: SourceRepositoryPort,
        extractor_factory: ExtractorFactoryPort,
        document_writer: DocumentWriterPort,
    ) -> None:
        self._documents = document_repository
        self._sources = source_repository
        self._extractor_factory = extractor_factory
        self._writer = document_writer

    async def execute(
        self,
        document_id: UUID,
        on_progress: DocumentProgressCallback | None = None,
    ) -> None:
        document = await self._documents.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError(
                f"Document '{document_id}' does not exist."
            )

        sources: list[Source] = []
        for raw_source in document.raw_sources:
            source = await self._sources.get_by_id(raw_source.id)
            if source is None:
                raise SourceNotFoundError(
                    f"Source '{raw_source.id}' does not exist."
                )
            sources.append(source)

        try:
            document.start_extraction()
            await self._documents.save(document)
            await self._report(document, on_progress)

            extracted_sources = await self._extract_sources(sources)

            if not extracted_sources:
                raise NoSourcesExtractedError(
                    "None of the provided sources could be extracted."
                )

            combined_content = "\n\n".join(
                f"[Fuente {i + 1}]\n{s.get_content()}"
                for i, s in enumerate(extracted_sources)
            )

            document.start_generation()
            await self._documents.save(document)
            await self._report(document, on_progress)

            title, sections, references = await self._writer.write(
                source_content=combined_content,
                title=document.title,
                document_type=document.document_type,
                presentation=document.presentation,
                additional_notes=document.additional_notes,
            )
            document.start_drafting()
            await self._documents.save(document)
            await self._report(document, on_progress)
            document.complete(
                title=title, sections=sections, sources=references
            )
            await self._documents.save(document)

        except Exception as exc:
            document.fail(str(exc))
            await self._documents.save(document)
            await self._report(document, on_progress)
            raise

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
