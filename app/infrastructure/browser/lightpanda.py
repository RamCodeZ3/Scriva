"""Playwright connections to the external Lightpanda CDP service."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Page, async_playwright


@asynccontextmanager
async def lightpanda_page(timeout_ms: int) -> AsyncIterator[Page]:
    """Isolate each source and release its context and CDP connection."""
    endpoint = os.environ.get("LIGHTPANDA_CDP_URL", "ws://127.0.0.1:9222")
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(
            endpoint, timeout=timeout_ms
        )
        try:
            context = await browser.new_context()
            try:
                page = await context.new_page()
                page.set_default_timeout(timeout_ms)
                yield page
            finally:
                await context.close()
        finally:
            await browser.close()
