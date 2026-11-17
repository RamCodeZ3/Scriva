from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time

from domain.value_objects.bib_metadata import BibMetadata

from application.ports.bib_metadata_port import MetadataEnricherPort


@dataclass(frozen=True)
class ExtractedSource:
    content: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    site_name: str | None = None
    canonical_url: str | None = None
    bib_metadata: BibMetadata | None = None

    @classmethod
    def enriched(cls, content: str, meta: BibMetadata) -> ExtractedSource:
        return cls(
            content=content,
            title=meta.title,
            author=meta.author,
            published_at=datetime.combine(meta.published_at, time())
            if meta.published_at
            else None,
            site_name=meta.site_name or meta.publisher,
            canonical_url=meta.url,
            bib_metadata=meta,
        )


class SourceExtractorPort(ABC):
    def __init__(
        self, metadata_enricher: MetadataEnricherPort | None = None
    ) -> None:
        self._metadata_enricher = metadata_enricher

    async def extract_with_metadata(self, raw: str) -> ExtractedSource:
        content = await self.extract(raw)
        enricher = getattr(self, "_metadata_enricher", None)
        if enricher is None:
            return ExtractedSource(content=content)
        meta = await enricher.enrich(
            raw, getattr(self, "_metadata_source_type", "auto")
        )
        return ExtractedSource.enriched(content, meta)

    @abstractmethod
    async def extract(self, raw: str) -> str:
        """
        Returns the extracted plain text content, ready to be sent to
        the AI writer. Implementations must raise
        `domain.exceptions.InvalidSourceError` when extraction fails
        (broken link, private video, unreadable file, etc).
        """
        raise NotImplementedError
