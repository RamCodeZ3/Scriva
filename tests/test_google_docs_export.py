from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from application.dtos.export_result import ExportResult
from domain.exceptions import DocumentBuildError
from googleapiclient.errors import HttpError
from infrastructure.export.document_exporter_resolver_adapter import (
    DocumentExporterResolverAdapter,
)
from infrastructure.export.google_docs_exporter_adapter import (
    _DOCX_MIME_TYPE,
    _GOOGLE_DOC_MIME_TYPE,
    GoogleDocsExporterAdapter,
)

from tests.test_export_table_of_contents import _document_fixture


class GoogleDocsExporterResolverTest(unittest.TestCase):
    def test_resolves_fresh_credentials_and_reuses_docx_renderer(self) -> None:
        user_id = uuid4()
        credentials_repository = AsyncMock()
        credentials_repository.get_refresh_token.side_effect = [
            "refresh-token-1",
            "refresh-token-2",
        ]
        token_provider = AsyncMock()
        token_provider.get_access_token.side_effect = [
            "access-token-1",
            "access-token-2",
        ]
        docx_exporter = AsyncMock()
        resolver = DocumentExporterResolverAdapter(
            pdf_exporter=object(),
            google_credentials_repository=credentials_repository,
            google_token_provider=token_provider,
            docx_exporter=docx_exporter,
        )

        first = asyncio.run(resolver.resolve("google_docs", user_id))
        second = asyncio.run(resolver.resolve("google_docs", user_id))

        self.assertIsNot(first, second)
        self.assertEqual(first._credentials.token, "access-token-1")
        self.assertEqual(second._credentials.token, "access-token-2")
        self.assertIs(first._docx_exporter, docx_exporter)
        self.assertEqual(
            credentials_repository.get_refresh_token.await_args_list,
            [unittest.mock.call(user_id), unittest.mock.call(user_id)],
        )
        self.assertEqual(
            token_provider.get_access_token.await_args_list,
            [
                unittest.mock.call("refresh-token-1"),
                unittest.mock.call("refresh-token-2"),
            ],
        )

    def test_keeps_legacy_google_doc_export_target(self) -> None:
        credentials_repository = AsyncMock()
        credentials_repository.get_refresh_token.return_value = "refresh"
        token_provider = AsyncMock()
        token_provider.get_access_token.return_value = "access"
        resolver = DocumentExporterResolverAdapter(
            pdf_exporter=object(),
            google_credentials_repository=credentials_repository,
            google_token_provider=token_provider,
        )

        exporter = asyncio.run(resolver.resolve("google_doc", uuid4()))

        self.assertEqual(exporter._credentials.token, "access")


class GoogleDocsConversionExporterTest(unittest.TestCase):
    @patch("infrastructure.export.google_docs_exporter_adapter.build")
    def test_renders_docx_and_uploads_it_for_native_conversion(
        self, build: Mock
    ) -> None:
        document = _document_fixture()
        docx_exporter = AsyncMock()
        docx_exporter.export.return_value = ExportResult(
            file_bytes=b"docx-content"
        )
        service = build.return_value
        create = service.files.return_value.create
        create.return_value.execute.return_value = {
            "id": "google-document-id",
            "webViewLink": "https://docs.google.com/document/d/link/edit",
        }
        exporter = GoogleDocsExporterAdapter("access", docx_exporter)

        result = asyncio.run(exporter.export(document))

        self.assertEqual(
            result.url, "https://docs.google.com/document/d/link/edit"
        )
        docx_exporter.export.assert_awaited_once_with(document)
        build.assert_called_once_with(
            "drive", "v3", credentials=exporter._credentials
        )
        call = create.call_args
        self.assertEqual(
            call.kwargs["body"],
            {"name": document.title, "mimeType": _GOOGLE_DOC_MIME_TYPE},
        )
        self.assertEqual(call.kwargs["fields"], "id, webViewLink")
        media = call.kwargs["media_body"]
        self.assertEqual(media.mimetype(), _DOCX_MIME_TYPE)
        self.assertTrue(media.resumable())

    @patch("infrastructure.export.google_docs_exporter_adapter.build")
    def test_builds_url_when_drive_omits_web_view_link(
        self, build: Mock
    ) -> None:
        execute = (
            build.return_value.files.return_value.create.return_value.execute
        )
        execute.return_value = {"id": "google-document-id"}
        exporter = GoogleDocsExporterAdapter("access")

        url = exporter._upload_and_convert(_document_fixture(), b"docx")

        self.assertEqual(
            url,
            "https://docs.google.com/document/d/google-document-id/edit",
        )

    @patch("infrastructure.export.google_docs_exporter_adapter.build")
    def test_requests_reauthorization_for_missing_drive_scope(
        self, build: Mock
    ) -> None:
        response = Mock(status=403, reason="Forbidden")
        error = HttpError(response, b'{"error": {"message": "forbidden"}}')
        execute = (
            build.return_value.files.return_value.create.return_value.execute
        )
        execute.side_effect = error
        exporter = GoogleDocsExporterAdapter("access")

        with self.assertRaisesRegex(DocumentBuildError, "drive.file scope"):
            exporter._upload_and_convert(_document_fixture(), b"docx")

    def test_rejects_empty_docx_render_result(self) -> None:
        docx_exporter = AsyncMock()
        docx_exporter.export.return_value = ExportResult(file_bytes=None)
        exporter = GoogleDocsExporterAdapter("access", docx_exporter)

        with self.assertRaisesRegex(DocumentBuildError, "no file content"):
            asyncio.run(exporter.export(_document_fixture()))
