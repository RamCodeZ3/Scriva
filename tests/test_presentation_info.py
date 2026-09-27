from __future__ import annotations

import unittest
from datetime import date

from api.schemas.documents import CreateDocumentRequest
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from infrastructure.ai.gemini_document_writer_adapter import (
    GeminiDocumentWriterAdapter,
)


class PresentationInfoTest(unittest.TestCase):
    def test_request_accepts_omitted_optional_cover_fields(self) -> None:
        request = CreateDocumentRequest(
            user="Student",
            document_type="report",
            sources=["Source text"],
        )

        self.assertIsNone(request.professor)
        self.assertIsNone(request.student_id)
        self.assertIsNone(request.institution)

    def test_missing_and_blank_values_become_editable_placeholders(
        self,
    ) -> None:
        presentation = PresentationInfo(
            student_name="Student",
            professor=None,
            student_id="  ",
            institution="",
        )

        self.assertEqual(presentation.professor, "<professor>")
        self.assertEqual(presentation.student_id, "<student_id>")
        self.assertEqual(presentation.institution, "<institution>")

    def test_prompt_includes_literal_placeholders(self) -> None:
        adapter = object.__new__(GeminiDocumentWriterAdapter)
        presentation = PresentationInfo(student_name="Student")

        prompt = adapter._build_prompt(
            source_content="Source text",
            title="Working title",
            document_type=DocumentType.REPORT,
            presentation=presentation,
            additional_notes=None,
        )

        self.assertIn("- professor: <professor>", prompt)
        self.assertIn("- student_id: <student_id>", prompt)
        self.assertIn("- institution: <institution>", prompt)

    def test_prompt_includes_current_date_for_cover_page(self) -> None:
        adapter = object.__new__(GeminiDocumentWriterAdapter)

        prompt = adapter._build_prompt(
            source_content="Source text",
            title="Working title",
            document_type=DocumentType.REPORT,
            presentation=PresentationInfo(student_name="Student"),
            additional_notes=None,
        )

        self.assertIn(f"- date: {date.today().isoformat()}", prompt)

    def test_real_values_are_trimmed_and_preserved(self) -> None:
        presentation = PresentationInfo(
            student_name="Student",
            professor="  Professor Smith  ",
            student_id="  12345  ",
            institution="  Scriva University  ",
        )

        self.assertEqual(presentation.professor, "Professor Smith")
        self.assertEqual(presentation.student_id, "12345")
        self.assertEqual(presentation.institution, "Scriva University")


if __name__ == "__main__":
    unittest.main()
