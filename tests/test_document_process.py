from __future__ import annotations

import unittest
from uuid import uuid4

from domain.entities.document_process import (
    DocumentProcess,
    DocumentProcessErrorStage,
    DocumentProcessStatus,
)
from domain.exceptions import DocumentProcessTransitionError


class DocumentProcessTest(unittest.TestCase):
    def test_generation_follows_its_state_machine(self) -> None:
        process = DocumentProcess.create_generation(uuid4(), [uuid4()])

        for status in (
            DocumentProcessStatus.EXTRACTING,
            DocumentProcessStatus.GENERATING,
            DocumentProcessStatus.DRAFTING,
            DocumentProcessStatus.DONE,
        ):
            process.transition_to(status)

        self.assertEqual(process.status, DocumentProcessStatus.DONE)

    def test_expansion_starts_extracting_and_cannot_generate(self) -> None:
        process = DocumentProcess.create_expansion(uuid4(), [uuid4()])

        with self.assertRaises(DocumentProcessTransitionError):
            process.transition_to(DocumentProcessStatus.GENERATING)

        process.transition_to(DocumentProcessStatus.EXPANDING)
        process.transition_to(DocumentProcessStatus.DRAFTING)
        process.transition_to(DocumentProcessStatus.DONE)

    def test_active_process_can_fail_with_user_safe_details(self) -> None:
        process = DocumentProcess.create_generation(uuid4(), [])

        process.fail(
            "Generation could not be completed.",
            DocumentProcessErrorStage.AI_GENERATION,
        )

        self.assertEqual(process.status, DocumentProcessStatus.FAILED)
        self.assertEqual(
            process.error_stage,
            DocumentProcessErrorStage.AI_GENERATION,
        )

    def test_terminal_process_rejects_failure(self) -> None:
        process = DocumentProcess.create_generation(uuid4(), [])
        process.fail("Failed", DocumentProcessErrorStage.INTERNAL)

        with self.assertRaises(DocumentProcessTransitionError):
            process.fail("Again", DocumentProcessErrorStage.INTERNAL)


if __name__ == "__main__":
    unittest.main()
