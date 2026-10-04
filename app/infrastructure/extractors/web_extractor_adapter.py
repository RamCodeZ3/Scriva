from __future__ import annotations

from datetime import datetime

from application.ports.source_extractor_port import (
    ExtractedSource,
    SourceExtractorPort,
)
from domain.exceptions import InvalidSourceError
from playwright.async_api import async_playwright


class WebExtractorAdapter(SourceExtractorPort):
    """
    Extracts the readable text of a web page, including pages rendered
    with JavaScript, using a headless Chromium instance via Playwright.
    """

    def __init__(
        self, timeout_ms: int = 30_000, wait_until: str = "networkidle"
    ) -> None:
        self._timeout_ms = timeout_ms
        self._wait_until = wait_until

    async def extract(self, raw: str) -> str:
        return (await self.extract_with_metadata(raw)).content

    async def extract_with_metadata(self, raw: str) -> ExtractedSource:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-images",
                        "--blink-settings=imagesEnabled=false",
                    ],
                )

                try:
                    page = await browser.new_page()

                    await page.route("**/*.", lambda route: route.abort())

                    await page.goto(
                        raw,
                        timeout=self._timeout_ms,
                        wait_until=self._wait_until,
                    )
                    metadata = await page.evaluate(
                        """() => ({
                            text: document.body.innerText,
                            title: document.querySelector(
                                'meta[property="og:title"]'
                            )?.content || document.title || null,
                            author: document.querySelector(
                                'meta[name="author"]'
                            )?.content || null,
                            published: document.querySelector(
                                'meta[property="article:published_time"]'
                            )?.content || null,
                            site: document.querySelector(
                                'meta[property="og:site_name"]'
                            )?.content || null,
                            canonical: document.querySelector(
                                'link[rel="canonical"]'
                            )?.href || location.href
                        })"""
                    )
                finally:
                    await browser.close()
        except Exception as exc:
            raise InvalidSourceError(
                f"Could not extract content from URL '{raw}': {exc}"
            ) from exc

        cleaned = _clean_text(metadata.get("text") or "")
        if not cleaned:
            raise InvalidSourceError(
                f"No readable text content found at '{raw}'."
            )
        return ExtractedSource(
            content=cleaned,
            title=_clean_metadata(metadata.get("title")),
            author=_clean_metadata(metadata.get("author")),
            published_at=_parse_datetime(metadata.get("published")),
            site_name=_clean_metadata(metadata.get("site")),
            canonical_url=_clean_metadata(metadata.get("canonical")) or raw,
        )


def _clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _clean_metadata(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _parse_datetime(value: object) -> datetime | None:
    cleaned = _clean_metadata(value)
    if cleaned is None:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
