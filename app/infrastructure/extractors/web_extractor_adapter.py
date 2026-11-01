from __future__ import annotations

from application.ports.bib_metadata_port import MetadataEnricherPort
from application.ports.source_extractor_port import (
    ExtractedSource,
    SourceExtractorPort,
)
from domain.exceptions import InvalidSourceError

from infrastructure.browser.lightpanda import lightpanda_page
from infrastructure.extractors.web_content import EXTRACT_WEB_CONTENT
from infrastructure.metadata.enricher import MetadataEnricherAdapter


class WebExtractorAdapter(SourceExtractorPort):
    """Read rendered page text and enrich from the same HTML snapshot."""

    def __init__(
        self,
        timeout_ms: int = 30_000,
        wait_until: str = "domcontentloaded",
        metadata_enricher: MetadataEnricherPort | None = None,
    ) -> None:
        super().__init__(metadata_enricher or MetadataEnricherAdapter())
        self._timeout_ms = timeout_ms
        self._wait_until = wait_until

    async def extract(self, raw: str) -> str:
        return (await self.extract_with_metadata(raw)).content

    async def extract_with_metadata(self, raw: str) -> ExtractedSource:
        try:
            async with lightpanda_page(self._timeout_ms) as page:
                await page.goto(
                    raw,
                    timeout=self._timeout_ms,
                    wait_until=self._wait_until,
                )
                text = await page.evaluate(EXTRACT_WEB_CONTENT)
                try:
                    html = await page.content()
                except Exception:
                    # Retain readable text if metadata HTML is unavailable.
                    html = ""
                final_url = page.url
        except Exception as exc:
            raise InvalidSourceError(
                f"Could not extract content from URL '{raw}': {exc}"
            ) from exc
        content = "\n".join(
            line.strip() for line in text.splitlines() if line.strip()
        )
        if not content:
            raise InvalidSourceError(
                f"No readable text content found at '{raw}'."
            )
        meta = await self._metadata_enricher.enrich(
            final_url, "web", html=html
        )
        return ExtractedSource.enriched(content, meta)
