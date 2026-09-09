from __future__ import annotations

import tempfile
import unittest

from application.dtos.document_dtos import UpdateDocumentInput
from application.dtos.export_result import ExportResult
from application.services.document_docx_cache import document_hash
from application.use_cases.get_document_use_case import GetDocumentUseCase
from application.use_cases.update_document_use_case import (
    UpdateDocumentUseCase,
)
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    HEADING_1,
    DocumentNode,
    text_node,
)
from infrastructure.cache.local_docx_cache import LocalDocxCacheService

from tests.test_export_table_of_contents import _document_fixture


class GetDocumentCacheAsideTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.cache = LocalDocxCacheService(
            self.temp_directory.name, size_limit=1024**2
        )
        self.document = _document_fixture()
        self.repository = _DocumentRepository(self.document)
        self.exporter = _CountingExporter()
        self.use_case = GetDocumentUseCase(
            self.repository, self.exporter, self.cache
        )

    async def asyncTearDown(self) -> None:
        self.cache.close()
        self.temp_directory.cleanup()

    async def test_compiles_on_miss_and_serves_subsequent_hit(self) -> None:
        first = await self.use_case.execute(
            self.document.id, self.document.user_id
        )
        second = await self.use_case.execute(
            self.document.id, self.document.user_id
        )

        self.assertEqual(first.file_bytes, b"compiled-docx")
        self.assertEqual(second.file_bytes, b"compiled-docx")
        self.assertEqual(self.exporter.calls, 1)
        self.assertEqual(self.repository.reads, 2)


class UpdateDocumentWriteThroughTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.cache = LocalDocxCacheService(
            self.temp_directory.name, size_limit=1024**2
        )
        self.document = _document_fixture()
        self.repository = _DocumentRepository(self.document)
        self.exporter = _CountingExporter()

    async def asyncTearDown(self) -> None:
        self.cache.close()
        self.temp_directory.cleanup()

    async def test_invalidates_old_hash_and_prewarms_updated_docx(
        self,
    ) -> None:
        old_hash = document_hash(self.cache, self.document)
        self.cache.set_docx(str(self.document.id), old_hash, b"stale")
        use_case = UpdateDocumentUseCase(
            self.repository,
            parser=None,
            exporter=self.exporter,
            cache=self.cache,
        )

        result = await use_case.execute(
            UpdateDocumentInput(
                document_id=self.document.id,
                user_id=self.document.user_id,
                title="Updated title",
            )
        )

        new_hash = document_hash(self.cache, self.document)
        self.assertNotEqual(old_hash, new_hash)
        self.assertIsNone(self.cache.get_docx(str(self.document.id), old_hash))
        self.assertEqual(
            self.cache.get_docx(str(self.document.id), new_hash),
            b"compiled-docx",
        )
        self.assertEqual(self.repository.saves, 1)
        self.assertEqual(result.file_bytes, b"compiled-docx")
        self.assertEqual(result.document.id, self.document.id)

    async def test_uses_cover_title_edited_inside_uploaded_docx(self) -> None:
        old_title = self.document.title
        parsed_sections = [
            (
                APASection(
                    section.section_type,
                    DocumentNode(
                        type=HEADING_1,
                        children=(text_node("Edited cover title"),),
                    ),
                    section.body_nodes,
                )
                if section.section_type is APASectionType.PRESENTATION
                else section
            )
            for section in self.document.sections
        ]
        use_case = UpdateDocumentUseCase(
            self.repository,
            parser=_StaticParser(parsed_sections),
            exporter=self.exporter,
            cache=self.cache,
        )

        await use_case.execute(
            UpdateDocumentInput(
                document_id=self.document.id,
                user_id=self.document.user_id,
                title=old_title,
                docx_bytes=b"uploaded-docx",
            )
        )

        self.assertEqual(self.document.title, "Edited cover title")


class _DocumentRepository:
    def __init__(self, document) -> None:
        self.document = document
        self.reads = 0
        self.saves = 0

    async def get_by_id(self, document_id):
        self.reads += 1
        return self.document if document_id == self.document.id else None

    async def save(self, document) -> None:
        self.document = document
        self.saves += 1


class _CountingExporter:
    def __init__(self) -> None:
        self.calls = 0

    async def export(self, document) -> ExportResult:
        self.calls += 1
        return ExportResult(
            file_bytes=b"compiled-docx",
            file_name=f"{document.id}.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )


class _StaticParser:
    def __init__(self, sections) -> None:
        self.sections = sections

    async def parse(self, content: bytes):
        return self.sections


if __name__ == "__main__":
    unittest.main()
