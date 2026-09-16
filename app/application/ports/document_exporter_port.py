from abc import ABC, abstractmethod

from domain.entities.document import Document

from application.dtos.export_result import ExportResult


class DocumentExporterPort(ABC):
    """
    Driven port for turning a finished Document into a real file.
    Adapters:
      - GoogleDocsExporterAdapter: renders DOCX and converts it to a native
        document in the user's own Google Drive.
      - PdfDocumentExporterAdapter: renders the document as a
        standalone APA 7 PDF with ReportLab and keeps a copy on the
        server's local disk.
    """

    @abstractmethod
    async def export(self, document: Document) -> ExportResult:
        """Returns the result of exporting the document (see ExportResult)."""
        raise NotImplementedError
