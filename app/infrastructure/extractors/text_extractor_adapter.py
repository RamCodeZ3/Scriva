from application.ports.bib_metadata_port import MetadataEnricherPort
from application.ports.source_extractor_port import SourceExtractorPort
from domain.exceptions import InvalidSourceError

from infrastructure.metadata.enricher import MetadataEnricherAdapter


class PlainTextExtractorAdapter(SourceExtractorPort):
    """No real extraction needed — the raw input already is the content."""

    _metadata_source_type = "text"

    def __init__(
        self, metadata_enricher: MetadataEnricherPort | None = None
    ) -> None:
        super().__init__(metadata_enricher or MetadataEnricherAdapter())

    async def extract(self, raw: str) -> str:
        content = raw.strip()
        if not content:
            raise InvalidSourceError("Plain text source is empty.")
        return content
