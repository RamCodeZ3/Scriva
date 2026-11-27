from __future__ import annotations

import asyncio

from application.ports.bib_metadata_port import MetadataEnricherPort
from application.ports.source_extractor_port import SourceExtractorPort
from domain.exceptions import InvalidSourceError
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from infrastructure.metadata.enricher import MetadataEnricherAdapter


class YoutubeExtractorAdapter(SourceExtractorPort):
    _metadata_source_type = "youtube"

    def __init__(
        self,
        preferred_langs: list[str] | None = None,
        metadata_enricher: MetadataEnricherPort | None = None,
    ) -> None:
        super().__init__(metadata_enricher or MetadataEnricherAdapter())
        self._preferred_langs = preferred_langs or ["es", "en"]

    async def extract(self, raw: str) -> str:
        video_id = self._extract_video_id(raw)
        try:
            transcript = await asyncio.to_thread(
                YouTubeTranscriptApi().fetch,
                video_id,
                languages=self._preferred_langs,
            )
        except (
            TranscriptsDisabled,
            NoTranscriptFound,
            VideoUnavailable,
        ) as exc:
            raise InvalidSourceError(
                f"No transcript available for '{raw}': {exc}"
            ) from exc
        except Exception as exc:
            raise InvalidSourceError(
                f"Could not extract transcript from '{raw}': {exc}"
            ) from exc

        text = " ".join(snippet.text for snippet in transcript)
        if not text.strip():
            raise InvalidSourceError(f"Transcript for '{raw}' is empty.")
        return text

    def _extract_video_id(self, raw: str) -> str:
        from infrastructure.metadata.common import youtube_id

        video_id = youtube_id(raw)
        if not video_id:
            raise InvalidSourceError(
                f"Could not parse a YouTube video id from '{raw}'."
            )
        return video_id
