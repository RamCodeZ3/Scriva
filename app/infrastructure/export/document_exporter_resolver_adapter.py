from __future__ import annotations

from uuid import UUID

from application.ports.document_exporter_port import DocumentExporterPort
from application.ports.document_exporter_resolver_port import (
    DocumentExporterResolverPort,
    UnsupportedExportTargetError,
)
from application.ports.google_credentials_port import GoogleCredentialsPort
from application.ports.google_oauth_token_port import GoogleOAuthTokenPort

from infrastructure.export.docx_document_exporter_adapter import (
    DocxDocumentExporterAdapter,
)
from infrastructure.export.google_docs_exporter_adapter import (
    GoogleDocsExporterAdapter,
)
from infrastructure.export.pdf_document_exporter_adapter import (
    PdfDocumentExporterAdapter,
)


class DocumentExporterResolverAdapter(DocumentExporterResolverPort):
    def __init__(
        self,
        pdf_exporter: PdfDocumentExporterAdapter,
        google_credentials_repository: GoogleCredentialsPort,
        google_token_provider: GoogleOAuthTokenPort,
        docx_exporter: DocumentExporterPort | None = None,
    ) -> None:
        self._pdf_exporter = pdf_exporter
        self._google_credentials_repository = google_credentials_repository
        self._google_token_provider = google_token_provider
        self._docx_exporter = docx_exporter or DocxDocumentExporterAdapter()

    async def resolve(
        self, export_target: str, user_id: UUID
    ) -> DocumentExporterPort:
        if export_target == "pdf":
            return self._pdf_exporter

        if export_target in {"google_doc", "google_docs"}:
            refresh_token = (
                await self._google_credentials_repository.get_refresh_token(
                    user_id
                )
            )
            if refresh_token is None:
                raise UnsupportedExportTargetError(
                    "This account hasn't granted Google Docs/Drive access yet."
                )
            access_token = await self._google_token_provider.get_access_token(
                refresh_token
            )
            return GoogleDocsExporterAdapter(
                user_access_token=access_token,
                docx_exporter=self._docx_exporter,
            )

        if export_target == "docx":
            return self._docx_exporter

        raise UnsupportedExportTargetError(
            f"Unknown export target '{export_target}'."
        )
