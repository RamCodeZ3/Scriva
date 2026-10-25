import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from api.v1.documents import _progressive_document_response
from application.dtos.document_dtos import (
    CreateDocumentInput,
    DocumentFileOutput,
    DocumentOutput,
    SourceErrorOutput,
)
from application.dtos.export_result import ExportResult
from application.use_cases.create_document_use_case import (
    CreateDocumentUseCase,
)
from domain.entities.document import DocumentStatus
from domain.entities.document_process import (
    DocumentProcess,
    DocumentProcessStatus,
)
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo

from tests.test_export_table_of_contents import _document_fixture


class ProgressiveDocumentStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_creation_confirms_done_after_process_is_saved(self) -> None:
        document = _document_fixture()
        document.status = DocumentStatus.DRAFTING
        process = DocumentProcess.create_generation(document.id, [])
        for state in (
            DocumentProcessStatus.EXTRACTING,
            DocumentProcessStatus.GENERATING,
            DocumentProcessStatus.DRAFTING,
        ):
            process.transition_to(state)

        processes = AsyncMock()
        processes.get_latest.return_value = process
        documents = AsyncMock()
        documents.get_by_id.return_value = document
        exporter = AsyncMock()
        exporter.export.return_value = ExportResult(
            file_bytes=b"generated-docx", file_name="result.docx"
        )
        use_case = CreateDocumentUseCase(
            document_repository=documents,
            process_repository=processes,
            source_repository=AsyncMock(),
            user_repository=AsyncMock(),
            job_dispatcher=AsyncMock(),
            exporter=exporter,
            cache=Mock(),
        )
        data = CreateDocumentInput(
            user_id=document.user_id,
            title=document.title,
            document_type=document.document_type,
            presentation=Mock(spec=PresentationInfo),
            sources=["Source content"],
        )

        async def operation(report):
            async def progress(metadata):
                self.assertEqual(process.status, DocumentProcessStatus.DONE)
                processes.save.assert_awaited_once_with(process)
                await report(metadata)

            result = await use_case.execute(data, on_progress=progress)
            self.assertEqual(result.document.status, DocumentStatus.DONE)
            return result

        response = _progressive_document_response(operation)
        body = b"".join([chunk async for chunk in response.body_iterator])

        self.assertEqual(_json_parts(body)[-1]["status"], "done")
        self.assertLess(body.index(b'"done"'), body.index(b"generated-docx"))

    async def test_streams_metadata_states_and_docx(self) -> None:
        metadata = _metadata(DocumentStatus.EXTRACTING)
        cleanup = Mock()

        async def operation(report):
            for state in (
                DocumentStatus.EXTRACTING,
                DocumentStatus.GENERATING,
                DocumentStatus.DRAFTING,
                DocumentStatus.DONE,
            ):
                await report(replace(metadata, status=state))
            return DocumentFileOutput(
                document=replace(metadata, status=DocumentStatus.DONE),
                file_bytes=b"docx-content",
                file_name="result.docx",
                content_type="application/docx",
            )

        response = _progressive_document_response(
            operation,
            cleanup=cleanup,
        )
        body = b"".join([chunk async for chunk in response.body_iterator])
        json_parts = _json_parts(body)

        self.assertEqual(
            [part["status"] for part in json_parts],
            ["extracting", "generating", "drafting", "done"],
        )
        self.assertEqual(
            json_parts[1]["sources_errors"],
            [
                {
                    "source_id": str(metadata.source_errors[0].source_id),
                    "error": "Unavailable",
                }
            ],
        )
        self.assertIn(b"Content-Disposition: attachment", body)
        self.assertIn(b"docx-content", body)
        cleanup.assert_called_once_with()

    async def test_streams_failed_metadata_for_fatal_error(self) -> None:
        async def operation(report):
            await report(_metadata(DocumentStatus.EXTRACTING))
            raise RuntimeError("Writer unavailable")

        response = _progressive_document_response(operation)
        body = b"".join([chunk async for chunk in response.body_iterator])
        json_parts = _json_parts(body)

        self.assertEqual(
            [part["status"] for part in json_parts],
            ["extracting", "failed"],
        )
        self.assertEqual(json_parts[-1]["error_message"], "Writer unavailable")
        self.assertEqual(json_parts[-1]["error_stage"], "internal")
        self.assertNotIn(b"Content-Disposition: attachment", body)


def _metadata(status: DocumentStatus) -> DocumentOutput:
    source_id = uuid4()
    now = datetime.now(UTC)
    return DocumentOutput(
        id=uuid4(),
        title="Test",
        document_type=DocumentType.REPORT,
        status=status,
        sections=[],
        user_id=uuid4(),
        error_message=None,
        source_ids=[source_id],
        source_errors=[
            SourceErrorOutput(
                source_id=source_id,
                raw="source",
                error="Unavailable",
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _json_parts(body: bytes) -> list[dict]:
    parts = body.split(b"--scriva-document-stream")
    return [
        json.loads(part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
        for part in parts
        if b"Content-Type: application/json" in part
    ]


if __name__ == "__main__":
    unittest.main()
