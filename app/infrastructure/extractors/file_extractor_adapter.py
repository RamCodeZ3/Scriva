from __future__ import annotations

import asyncio
import os

from application.ports.source_extractor_port import SourceExtractorPort
from domain.exceptions import InvalidSourceError

_DOCUMENT_EXTENSIONS = {".txt", ".pdf", ".docx", ".doc", ".odt", ".rtf"}


class FileExtractorAdapter(SourceExtractorPort):
    def __init__(
        self,
        max_chars: int | None = 200_000,
        media_extractor: SourceExtractorPort | None = None,
    ) -> None:
        self._max_chars = max_chars
        self._media_extractor = media_extractor

    async def extract(self, raw: str) -> str:
        if not os.path.isfile(raw):
            raise InvalidSourceError(f"File not found: '{raw}'.")

        ext = os.path.splitext(raw)[1].lower()

        if ext not in _DOCUMENT_EXTENSIONS:
            if self._media_extractor is None:
                raise InvalidSourceError(
                    f"Unsupported file extension: '{ext}'."
                )
            content = await self._media_extractor.extract(raw)
        else:
            try:
                content = await asyncio.to_thread(self._read_sync, raw, ext)
            except InvalidSourceError:
                raise
            except Exception as exc:
                raise InvalidSourceError(
                    f"Could not read file '{raw}': {exc}"
                ) from exc

        content = content.strip()
        if not content:
            raise InvalidSourceError(f"File '{raw}' has no extractable text.")

        if self._max_chars is not None:
            content = content[: self._max_chars]

        return content

    def _read_sync(self, path: str, ext: str) -> str:
        if ext == ".txt":
            return self._read_txt(path)
        if ext == ".pdf":
            return self._read_pdf(path)
        if ext == ".docx":
            return self._read_docx(path)
        raise InvalidSourceError(f"Unsupported file extension: '{ext}'.")

    @staticmethod
    def _read_txt(path: str) -> str:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()

    @staticmethod
    def _read_pdf(path: str) -> str:
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    @staticmethod
    def _read_docx(path: str) -> str:
        import docx

        document = docx.Document(path)
        paragraphs = [p.text for p in document.paragraphs]
        return "\n".join(paragraphs)
