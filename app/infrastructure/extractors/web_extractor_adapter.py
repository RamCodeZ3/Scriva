from __future__ import annotations

from playwright.async_api import async_playwright

from domain.exceptions import InvalidSourceError

from application.ports.source_extractor_port import SourceExtractorPort


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
                    text = await page.evaluate("() => document.body.innerText")
                finally:
                    await browser.close()
        except Exception as exc:
            raise InvalidSourceError(
                f"Could not extract content from URL '{raw}': {exc}"
            ) from exc

        cleaned = _clean_text(text)
        if not cleaned:
            raise InvalidSourceError(
                f"No readable text content found at '{raw}'."
            )
        return cleaned


def _clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)
