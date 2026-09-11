from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
