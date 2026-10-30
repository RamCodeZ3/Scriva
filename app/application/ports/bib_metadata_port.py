"""Common enrichment contract; the value object also belongs to the domain."""

from abc import ABC, abstractmethod

from domain.value_objects.bib_metadata import BibMetadata as BibMetadata


class MetadataEnricherPort(ABC):
    @abstractmethod
    async def enrich(
        self, raw: str, source_type: str = "auto", *, html: str | None = None
    ) -> BibMetadata:
        """Return available verified metadata, even if providers fail."""
