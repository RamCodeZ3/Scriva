from __future__ import annotations

import asyncio
from io import BytesIO

from application.dtos.export_result import ExportResult
from application.ports.document_exporter_port import DocumentExporterPort
from domain.entities.document import Document
from domain.exceptions import DocumentBuildError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from infrastructure.export.docx_document_exporter_adapter import (
    DocxDocumentExporterAdapter,
)

_DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"


class GoogleDocsExporterAdapter(DocumentExporterPort):
    """Render with the DOCX engine and convert the upload in Google Drive."""

    def __init__(
        self,
        user_access_token: str,
        docx_exporter: DocumentExporterPort | None = None,
    ) -> None:
        self._credentials = Credentials(token=user_access_token)
        self._docx_exporter = docx_exporter or DocxDocumentExporterAdapter()

    async def export(self, document: Document) -> ExportResult:
        docx_result = await self._docx_exporter.export(document)
        if not docx_result.file_bytes:
            raise DocumentBuildError(
                "DOCX rendering returned no file content for Google Docs."
            )
        url = await asyncio.to_thread(
            self._upload_and_convert,
            document,
            docx_result.file_bytes,
        )
        return ExportResult(url=url)

    def _upload_and_convert(
        self, document: Document, docx_bytes: bytes
    ) -> str:
        service = build("drive", "v3", credentials=self._credentials)
        media = MediaIoBaseUpload(
            BytesIO(docx_bytes),
            mimetype=_DOCX_MIME_TYPE,
            resumable=True,
        )
        try:
            created = (
                service.files()
                .create(
                    body={
                        "name": document.title,
                        "mimeType": _GOOGLE_DOC_MIME_TYPE,
                    },
                    media_body=media,
                    fields="id, webViewLink",
                )
                .execute()
            )
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 403:
                raise DocumentBuildError(
                    "Google Docs export requires renewed Google Drive "
                    "authorization with the drive.file scope."
                ) from exc
            raise DocumentBuildError(
                f"Google Docs export failed: {exc}"
            ) from exc

        document_id = created.get("id")
        if not document_id:
            raise DocumentBuildError(
                "Google Drive conversion returned no document id."
            )
        return created.get("webViewLink") or (
            f"https://docs.google.com/document/d/{document_id}/edit"
        )
