from __future__ import annotations

import asyncio
import copy
from collections import OrderedDict
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

from application.ports.bib_metadata_port import MetadataEnricherPort
from domain.value_objects.bib_metadata import BibMetadata

from infrastructure.metadata.common import (
    TIMEOUT,
    file_title,
    logger,
    normalize_title,
    youtube_id,
)
from infrastructure.metadata.crossref import enrich_crossref
from infrastructure.metadata.http import MetadataHTTPClient
from infrastructure.metadata.media import read_audio, read_ffprobe
from infrastructure.metadata.office import read_office
from infrastructure.metadata.pdf import read_pdf
from infrastructure.metadata.web import read_web
from infrastructure.metadata.youtube import enrich_youtube


def detect_type(raw: str) -> str:
    if youtube_id(raw):
        return "youtube"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return "web" if raw.startswith(("http://", "https://")) else "text"
    if parsed.scheme in {"http", "https"}:
        return "web"
    ext = Path(raw).suffix.lower()
    if ext in {".pdf", ".docx", ".pptx"}:
        return ext[1:]
    if ext in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}:
        return "audio"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "video"
    return "text"


class MetadataEnricherAdapter(MetadataEnricherPort):
    def __init__(
        self,
        *,
        youtube_api_key: str | None = None,
        crossref_email: str | None = None,
        http: MetadataHTTPClient | None = None,
    ) -> None:
        agent = "Scriva/1.6"
        if crossref_email:
            agent += f" (mailto:{crossref_email})"
        self._http = http or MetadataHTTPClient(agent)
        self._youtube_api_key = youtube_api_key
        self._cache: OrderedDict[str, tuple[float, BibMetadata]] = (
            OrderedDict()
        )

    async def enrich(
        self, raw: str, source_type: str = "auto", *, html: str | None = None
    ) -> BibMetadata:
        kind = (
            detect_type(raw)
            if source_type in {"auto", "file"}
            else (source_type)
        )
        meta = BibMetadata(source_type=kind)
        cache_key = f"{kind}:{youtube_id(raw) or raw}"
        cached = self._cache.get(cache_key)
        if kind == "youtube" and cached and monotonic() - cached[0] < 3600:
            self._cache.move_to_end(cache_key)
            return copy.deepcopy(cached[1])
        try:
            if kind == "youtube":
                await enrich_youtube(
                    meta, raw, self._http, self._youtube_api_key
                )
            elif kind == "web":
                if html is None:
                    # The production extractor passes its rendered HTML.
                    from playwright.async_api import async_playwright

                    async with async_playwright() as pw:
                        browser = await pw.chromium.launch(headless=True)
                        try:
                            page = await browser.new_page()
                            await page.goto(
                                raw,
                                timeout=TIMEOUT * 1000,
                                wait_until="domcontentloaded",
                            )
                            html = await page.content()
                            raw = page.url
                        finally:
                            await browser.close()
                await asyncio.to_thread(read_web, meta, html, raw)
            elif kind in {"pdf", "docx", "pptx"}:
                reader = read_pdf if kind == "pdf" else read_office
                meta.needs_review = True
                await asyncio.to_thread(reader, meta, raw)
            elif kind in {"audio", "video"}:
                meta.needs_review = True
                if kind == "audio":
                    try:
                        await asyncio.to_thread(read_audio, meta, raw)
                    except Exception:
                        logger.info("Audio tags unavailable; trying ffprobe.")
                if (
                    not meta.title
                    or not meta.author
                    or not (meta.published_at or meta.published_year)
                ):
                    await asyncio.to_thread(read_ffprobe, meta, raw)
            else:
                meta.needs_review = True
        except Exception:
            # Metadata failure cannot invalidate extracted text.
            logger.info("Metadata enrichment incomplete for type %s.", kind)
            meta.needs_review = True
        if kind in {"pdf", "docx", "pptx", "audio", "video"} or (
            kind == "text"
            and (
                source_type == "file"
                or (
                    source_type == "auto"
                    and Path(raw).suffix.lower() == ".txt"
                )
            )
        ):
            file_title(meta, raw)
        if meta.doi:
            await enrich_crossref(meta, self._http)
            # Retained local fields remain explicitly marked for review.
            meta.needs_review = any(
                origin
                in {"pdf_info", "doc_properties", "media_tags", "ninguno"}
                for field, origin in meta.origins.items()
                if field != "doi"
            )
        normalize_title(meta)
        if (
            not meta.title
            or not meta.author
            or not (meta.published_at or meta.published_year)
        ):
            meta.needs_review = True
        if (
            kind == "youtube"
            and meta.title
            and meta.author
            and (meta.published_at or meta.published_year)
        ):
            self._cache[cache_key] = (monotonic(), copy.deepcopy(meta))
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
        return meta
