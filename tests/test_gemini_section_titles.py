from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from domain.entities.source import Source, SourceType
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    HEADING_1,
    PARAGRAPH,
    DocumentNode,
)
from domain.value_objects.document_type import DocumentType
from infrastructure.ai.gemini_document_writer_adapter import (
    GeminiDocumentWriterAdapter,
    _add_table_titles,
)


class GeminiSectionTitleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = object.__new__(GeminiDocumentWriterAdapter)

    def test_preserves_content_specific_introduction_title(self) -> None:
        section = self.adapter._build_section(
            _raw_introduction("Retos éticos de la inteligencia artificial"),
            introduction_fallback="Inteligencia artificial y sociedad",
        )

        self.assertEqual(section.section_type, APASectionType.INTRODUCTION)
        self.assertEqual(
            section.title,
            "Retos éticos de la inteligencia artificial",
        )

    def test_replaces_generic_introduction_with_document_title(self) -> None:
        section = self.adapter._build_section(
            _raw_introduction("Introducción"),
            introduction_fallback="Inteligencia artificial y sociedad",
        )

        self.assertEqual(section.title, "Inteligencia artificial y sociedad")

    def test_uses_document_title_for_presentation_heading(self) -> None:
        raw = _raw_introduction("Presentación")
        raw["section_type"] = "presentation"

        section = self.adapter._build_section(
            raw,
            introduction_fallback="Inteligencia artificial y sociedad",
        )

        self.assertEqual(section.title, "Inteligencia artificial y sociedad")

    def test_rejects_generic_title_without_specific_fallback(self) -> None:
        with self.assertRaises(DocumentBuildError):
            self.adapter._build_section(
                _raw_introduction("Introduction"),
                introduction_fallback="Introducción",
            )

    def test_augment_request_excludes_presentation_nodes(self) -> None:
        presentation = _section(
            APASectionType.PRESENTATION,
            "Private edited cover",
        )
        introduction = _section(
            APASectionType.INTRODUCTION,
            "A specific introduction",
        )

        prompt = self.adapter._build_augment_prompt(
            existing_sections=[presentation, introduction],
            existing_references=[],
            new_content="New material",
            document_type=DocumentType.REPORT,
            additional_notes=None,
        )

        self.assertNotIn("Private edited cover", prompt)
        self.assertNotIn('"section_type": "presentation"', prompt)
        self.assertIn("A specific introduction", prompt)

    def test_augment_prompt_lists_all_valid_source_ids_and_facts(self) -> None:
        first = _source(SourceType.WEB)
        second = _source(SourceType.TEXT)

        prompt = self.adapter._build_augment_prompt(
            existing_sections=[
                _section(APASectionType.BODY, "Existing content")
            ],
            existing_references=[],
            new_content="New material",
            document_type=DocumentType.SUMMARY,
            additional_notes=None,
            sources=[first, second],
        )

        self.assertIn("2 successfully extracted source(s)", prompt)
        self.assertIn(str(first.id), prompt)
        self.assertIn(str(second.id), prompt)
        self.assertIn("every new\nsubstantive claim", prompt)

    def test_model_references_are_ignored_even_when_malformed(self) -> None:
        response = """{
            "title": "Specific title",
            "sections": [{
                "section_type": "body",
                "title": "Body",
                "nodes": [{"type": "paragraph", "children": [
                    {"text": "Supported content"}
                ]}]
            }],
            "references": "invented and malformed"
        }"""

        _, _, references, _ = self.adapter._parse_response(
            response, document_type=DocumentType.SUMMARY
        )

        self.assertEqual(references, [])

    def test_tables_are_numbered_across_sections_in_spanish(self) -> None:
        first = _table_section(
            APASectionType.INTRODUCTION, "Como muestra la Tabla 1."
        )
        second = _table_section(
            APASectionType.BODY, "Como muestra la Tabla 2."
        )

        result = _add_table_titles([first, second], "es")

        self.assertEqual(result[0].body_nodes[1].plain_text(), "Tabla 1")
        self.assertEqual(result[1].body_nodes[1].plain_text(), "Tabla 2")

        repeated = _add_table_titles(result, "es")

        self.assertEqual(repeated, result)


def _raw_introduction(title: str) -> dict:
    return {
        "section_type": "introduction",
        "title": title,
        "nodes": [
            {
                "type": "paragraph",
                "styles": {"textAlign": "justify"},
                "children": [{"text": "Contenido introductorio."}],
            }
        ],
    }


def _section(section_type: APASectionType, text: str) -> APASection:
    leaf = DocumentNode(text=text)
    return APASection(
        section_type=section_type,
        heading=DocumentNode(type=HEADING_1, children=(leaf,)),
        body_nodes=(DocumentNode(type=PARAGRAPH, children=(leaf,)),),
    )


def _source(source_type: SourceType) -> Source:
    source = Source.create("content", source_type, uuid4())
    source.mark_extracted(
        "Extracted content",
        title="Known title",
        published_at=datetime(2023, 1, 1, tzinfo=UTC),
    )
    return source


def _table_section(
    section_type: APASectionType, reference_text: str
) -> APASection:
    table = DocumentNode(
        type="table",
        caption="Comparison",
        children=(
            DocumentNode(
                type="table-row",
                children=(
                    DocumentNode(
                        type="table-cell",
                        children=(
                            DocumentNode(
                                type=PARAGRAPH,
                                children=(DocumentNode(text="Value"),),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    return APASection(
        section_type=section_type,
        heading=DocumentNode(
            type=HEADING_1, children=(DocumentNode(text="Heading"),)
        ),
        body_nodes=(
            DocumentNode(
                type=PARAGRAPH,
                children=(DocumentNode(text=reference_text),),
            ),
            table,
        ),
    )


if __name__ == "__main__":
    unittest.main()
