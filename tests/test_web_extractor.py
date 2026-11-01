"""Web extraction and Lightpanda connection lifecycle tests."""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from domain.exceptions import InvalidSourceError
from domain.value_objects.bib_metadata import BibMetadata
from infrastructure.browser.lightpanda import lightpanda_page
from infrastructure.extractors.web_extractor_adapter import WebExtractorAdapter
from infrastructure.metadata.enricher import MetadataEnricherAdapter


class WebExtractorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = MagicMock()
        self.page.goto = AsyncMock()
        self.page.evaluate = AsyncMock(
            return_value="  First paragraph  \n\n Second paragraph "
        )
        self.page.content = AsyncMock(return_value="<title>Article</title>")
        self.page.url = "https://example.test/final"
        self.session = MagicMock()
        self.session.return_value.__aenter__ = AsyncMock(
            return_value=self.page
        )
        self.session.return_value.__aexit__ = AsyncMock(return_value=False)
        self.enricher = MagicMock()
        self.enricher.enrich = AsyncMock(
            return_value=BibMetadata(source_type="web", title="Article")
        )
        self.extractor = WebExtractorAdapter(metadata_enricher=self.enricher)
        self.mock_session = patch(
            "infrastructure.extractors.web_extractor_adapter.lightpanda_page",
            self.session,
        )
        self.mock_session.start()
        self.addCleanup(self.mock_session.stop)

    async def test_text_and_metadata_share_redirected_snapshot(self):
        result = await self.extractor.extract_with_metadata(
            "https://example.test/start"
        )
        self.assertEqual(result.content, "First paragraph\nSecond paragraph")
        self.assertEqual(result.title, "Article")
        self.page.goto.assert_awaited_once_with(
            "https://example.test/start",
            timeout=30_000,
            wait_until="domcontentloaded",
        )
        self.enricher.enrich.assert_awaited_once_with(
            self.page.url, "web", html="<title>Article</title>"
        )

    async def test_metadata_snapshot_failure_retains_text(self):
        self.page.content.side_effect = RuntimeError("Snapshot unavailable")
        result = await self.extractor.extract_with_metadata(self.page.url)
        self.assertTrue(result.content)
        self.assertEqual(self.enricher.enrich.call_args.kwargs, {"html": ""})

    async def test_navigation_failure_becomes_source_error(self):
        self.page.goto.side_effect = RuntimeError("Navigation failed")
        with self.assertRaises(InvalidSourceError):
            await self.extractor.extract(self.page.url)
        self.session.return_value.__aexit__.assert_awaited_once()
        self.enricher.enrich.assert_not_awaited()

    async def test_empty_text_becomes_source_error(self):
        self.page.evaluate.return_value = " \n "
        with self.assertRaises(InvalidSourceError):
            await self.extractor.extract(self.page.url)


class LightpandaConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_isolated_context_closes_on_success_and_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                page = MagicMock()
                context = MagicMock()
                context.new_page = AsyncMock(return_value=page)
                context.close = AsyncMock()
                browser = MagicMock()
                browser.new_context = AsyncMock(return_value=context)
                browser.close = AsyncMock()
                pw = MagicMock()
                pw.chromium.connect_over_cdp = AsyncMock(return_value=browser)
                manager = MagicMock()
                manager.__aenter__ = AsyncMock(return_value=pw)
                manager.__aexit__ = AsyncMock(return_value=False)
                with (
                    patch.dict(
                        os.environ, {"LIGHTPANDA_CDP_URL": "ws://lp:9222"}
                    ),
                    patch(
                        "infrastructure.browser.lightpanda.async_playwright",
                        return_value=manager,
                    ),
                ):
                    try:
                        async with lightpanda_page(1234) as actual:
                            self.assertIs(actual, page)
                            if fail:
                                raise RuntimeError("Extraction failed")
                    except RuntimeError:
                        self.assertTrue(fail)
                pw.chromium.connect_over_cdp.assert_awaited_once_with(
                    "ws://lp:9222", timeout=1234
                )
                pw.chromium.launch.assert_not_called()
                page.set_default_timeout.assert_called_once_with(1234)
                context.close.assert_awaited_once()
                browser.close.assert_awaited_once()

    async def test_standalone_metadata_uses_lightpanda(self):
        page = MagicMock()
        page.goto = AsyncMock()
        page.content = AsyncMock(
            return_value=(
                "<title>Standalone</title>"
                '<meta name="citation_publication_date" content="2024-01-02">'
            )
        )
        page.url = "https://example.test/final"
        session = MagicMock()
        session.return_value.__aenter__ = AsyncMock(return_value=page)
        session.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch(
            "infrastructure.browser.lightpanda.lightpanda_page", session
        ):
            meta = await MetadataEnricherAdapter().enrich(page.url, "web")
        self.assertEqual(meta.title, "Standalone")
        session.return_value.__aexit__.assert_awaited_once()
