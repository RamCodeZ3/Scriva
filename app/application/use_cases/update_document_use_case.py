from domain.value_objects.apa_structure import APASectionType

from application.dtos.document_dtos import (
    DocumentFileOutput,
    UpdateDocumentInput,
    document_to_output,
)
from application.exceptions import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
)
from application.ports.document_exporter_port import DocumentExporterPort
from application.ports.document_parser_port import DocumentParserPort
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.docx_cache_port import DocxCachePort
from application.services.document_docx_cache import cache_docx
from application.services.document_edit_merge import merge_docx_edits


class UpdateDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepositoryPort,
        parser: DocumentParserPort,
        exporter: DocumentExporterPort,
        cache: DocxCachePort,
    ) -> None:
        self._documents = document_repository
        self._parser = parser
        self._exporter = exporter
        self._cache = cache

    async def execute(self, data: UpdateDocumentInput) -> DocumentFileOutput:
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

        sections = data.sections
        title = data.title
        if data.docx_bytes is not None:
            parsed_sections = await self._parser.parse(data.docx_bytes)
            sections = merge_docx_edits(document.sections, parsed_sections)
            presentation = next(
                (
                    section
                    for section in parsed_sections
                    if section.section_type is APASectionType.PRESENTATION
                ),
                None,
            )
            if presentation is not None and (
                title is None or title == document.title
            ):
                title = presentation.title

        document.update_content(
            title=title,
            sections=sections,
        )
        await self._documents.save(document)

        # Always compile the persisted model. Browser-based DOCX editors can
        # silently flatten complex OOXML fields (notably the TOC), page-break
        # paragraphs, and paragraph styles even when the user made no change.
        # Parsing first and exporting here restores Scriva's canonical
        # structure while retaining the supported user edits.
        exported = await self._exporter.export(document)
        if exported.file_bytes is None:
            raise RuntimeError("The DOCX exporter returned no binary content.")
        docx_bytes = exported.file_bytes
        await cache_docx(
            self._cache,
            document,
            docx_bytes,
            invalidate_existing=True,
        )

        return DocumentFileOutput(
            document=document_to_output(document),
            file_bytes=docx_bytes,
            file_name=exported.file_name or f"{document.title}.docx",
            content_type=(
                exported.content_type
                or "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )
