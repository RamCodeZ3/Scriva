import asyncio
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from domain.entities.document import Document, DocumentStatus
from domain.value_objects.apa_structure import (
    APA7_DOCUMENT_STYLES,
    APASection,
    APASectionType,
)
from domain.value_objects.document_node import (
    HEADING_1,
    PARAGRAPH,
    DocumentNode,
    text_node,
)
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

        self.assertEqual(
            row["node_tree"],
            {
                "type": "document",
                "meta": {
                    "title": "Schema mapping",
                    "style_guide": "APA7",
                },
                "global_style": APA7_DOCUMENT_STYLES,
                "children": [],
            },
        )
        self.assertNotIn("document_style", row)
        self.assertNotIn("sections", row)
        self.assertNotIn("document_styles", row)
        self.assertNotIn("presentation", row)
        self.assertNotIn("additional_notes", row)

    def test_reads_current_document_columns(self) -> None:
        row = self.repository._to_row(self.document)

        restored = asyncio.run(self.repository._to_entity(row))

        self.assertEqual(restored.sections, [])
        self.assertEqual(restored.global_style, APA7_DOCUMENT_STYLES)

    def test_reads_legacy_style_column_and_section_array(self) -> None:
        row = self.repository._to_row(self.document)
        row["node_tree"] = []
        row["document_style"] = {"fontSize": "14pt"}

        restored = asyncio.run(self.repository._to_entity(row))

        self.assertEqual(restored.global_style["fontSize"], "14pt")
        self.assertEqual(
            restored.global_style["fontFamily"], "Times New Roman, serif"
        )

    def test_round_trips_sections_through_root_children(self) -> None:
        self.document.sections = [
            APASection(
                section_type=APASectionType.INTRODUCTION,
                heading=DocumentNode(
                    type=HEADING_1,
                    section_type="introduction",
                    children=(text_node("A specific introduction"),),
                ),
                body_nodes=(
                    DocumentNode(
                        type=PARAGRAPH,
                        section_type="introduction",
                        children=(text_node("Content"),),
                    ),
                ),
            )
        ]
        self.document.global_style["fontSize"] = "14pt"

        row = self.repository._to_row(self.document)
        restored = asyncio.run(self.repository._to_entity(row))

        self.assertEqual(len(row["node_tree"]["children"]), 2)
        self.assertEqual(restored.sections[0].title, "A specific introduction")
        self.assertEqual(
            restored.sections[0].body_nodes[0].plain_text(), "Content"
        )
        self.assertEqual(
            restored.sections[0].body_nodes[0].section_type, "introduction"
        )
        self.assertEqual(restored.global_style["fontSize"], "14pt")

    def test_reads_root_nodes_with_section_type_only_on_heading(self) -> None:
        row = self.repository._to_row(self.document)
        row["node_tree"]["children"] = [
            {
                "type": "heading-1",
                "section_type": "introduction",
                "children": [{"text": "A specific introduction"}],
            },
            {
                "type": "paragraph",
                "children": [{"text": "Content without repeated metadata"}],
            },
        ]

        restored = asyncio.run(self.repository._to_entity(row))

        body = restored.sections[0].body_nodes[0]
        self.assertEqual(body.section_type, "introduction")

    def test_infers_sections_from_canonical_heading_order(self) -> None:
        row = self.repository._to_row(self.document)
        row["node_tree"]["children"] = [
            {
                "type": "heading-1",
                "children": [{"text": "Document title"}],
            },
            {"type": "paragraph", "children": [{"text": "Student"}]},
            {"type": "page-break"},
            {
                "type": "heading-1",
                "children": [{"text": "Table of contents"}],
            },
            {"type": "table-of-contents", "children": []},
        ]

        restored = asyncio.run(self.repository._to_entity(row))

        self.assertEqual(
            [section.section_type for section in restored.sections],
            [APASectionType.PRESENTATION, APASectionType.INDEX],
        )
        self.assertTrue(
            all(
                node.section_type == section.section_type.value
                for section in restored.sections
                for node in section.nodes
            )
        )


class _EmptySourceRepository:
    async def get_by_id(self, source_id):
        raise AssertionError(f"Unexpected source lookup: {source_id}")


if __name__ == "__main__":
    unittest.main()
