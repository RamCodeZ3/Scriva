from __future__ import annotations

import asyncio

import yt_dlp
from domain.value_objects.bib_metadata import BibMetadata

from infrastructure.metadata.common import (
    TIMEOUT,
    logger,
    put,
    set_date,
    timestamp_date,
    youtube_id,
)
from infrastructure.metadata.http import MetadataHTTPClient


def _extract_info(url: str) -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": TIMEOUT,
        "retries": 0,
        "extractor_retries": 0,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    return info if isinstance(info, dict) else {}


async def enrich_youtube(
    meta: BibMetadata,
    raw: str,
    http: MetadataHTTPClient,
    api_key: str | None,
) -> None:
    video_id = youtube_id(raw)
    if not video_id:
        meta.needs_review = True
        return
    url = f"https://www.youtube.com/watch?v={video_id}"
    # These values are verifiable from the input URL, independent of providers.
    put(meta, "url", url, "ninguno")
    put(meta, "site_name", "YouTube", "ninguno")
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_extract_info, url), TIMEOUT
        )
        put(meta, "title", info.get("title"), "yt_dlp")
        put(
            meta,
            "author",
            info.get("channel") or info.get("uploader"),
            "yt_dlp",
        )
        set_date(meta, info.get("upload_date"), "yt_dlp")
        if not meta.published_at:
            set_date(meta, timestamp_date(info.get("timestamp")), "yt_dlp")
        duration = info.get("duration")
        if isinstance(duration, (float, int)) and duration >= 0:
            put(meta, "duration_seconds", int(duration), "yt_dlp")
        if info:
            meta.origins["url"] = "yt_dlp"
            meta.origins["site_name"] = "yt_dlp"
    except Exception:
        logger.info("YouTube primary metadata unavailable; trying fallback.")
    if not meta.title or not meta.author:
        try:
            info = await http.get_json(
                "https://www.youtube.com/oembed",
                {"url": url, "format": "json"},
            )
            put(meta, "title", info.get("title"), "oembed")
            put(meta, "author", info.get("author_name"), "oembed")
        except Exception:
            logger.info("YouTube oEmbed metadata unavailable.")
    if api_key and (
        not meta.title
        or not meta.author
        or not (meta.published_at or meta.published_year)
    ):
        try:
            info = await http.get_json(
                "https://www.googleapis.com/youtube/v3/videos",
                {"part": "snippet", "id": video_id, "key": api_key},
            )
            items = info.get("items") or []
            snippet = items[0].get("snippet", {}) if items else {}
            put(meta, "title", snippet.get("title"), "youtube_api")
            put(meta, "author", snippet.get("channelTitle"), "youtube_api")
            set_date(meta, snippet.get("publishedAt"), "youtube_api")
        except Exception:
            logger.info("YouTube Data API metadata unavailable.")
