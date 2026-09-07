import asyncio
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from domain.entities.document import Document, DocumentStatus
from domain.value_objects.apa_structure import APA7_DOCUMENT_STYLES
from domain.value_objects.document_type import DocumentType
from infrastructure.persistence.supabase_document_repository import (
    SupabaseDocumentRepository,
)


class SupabaseDocumentRepositoryMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SupabaseDocumentRepository(
            client=None,
            source_repository=_EmptySourceRepository(),
        )
        now = datetime.now(UTC)
        self.document = Document(
            id=uuid4(),
            user_id=uuid4(),
            title="Schema mapping",
            document_type=DocumentType.REPORT,
            raw_sources=[],
            status=DocumentStatus.PENDING,
            sections=[],
            sources=[],
            created_at=now,
            updated_at=now,
        )

    def test_writes_only_current_document_columns(self) -> None:
        row = self.repository._to_row(self.document)

        self.assertEqual(row["node_tree"], [])
        self.assertEqual(row["document_style"], APA7_DOCUMENT_STYLES)
        self.assertNotIn("sections", row)
        self.assertNotIn("document_styles", row)
        self.assertNotIn("presentation", row)
        self.assertNotIn("additional_notes", row)

    def test_reads_current_document_columns(self) -> None:
        row = self.repository._to_row(self.document)

        restored = asyncio.run(self.repository._to_entity(row))

        self.assertEqual(restored.sections, [])
        self.assertEqual(restored.document_style, APA7_DOCUMENT_STYLES)


class _EmptySourceRepository:
    async def get_by_id(self, source_id):
        raise AssertionError(f"Unexpected source lookup: {source_id}")


if __name__ == "__main__":
    unittest.main()
