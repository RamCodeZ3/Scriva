from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExtractedSource:
    content: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    site_name: str | None = None
    canonical_url: str | None = None


class SourceExtractorPort(ABC):
    async def extract_with_metadata(self, raw: str) -> ExtractedSource:
        return ExtractedSource(content=await self.extract(raw))

    @abstractmethod
    async def extract(self, raw: str) -> str:
        """
        Returns the extracted plain text content, ready to be sent to
        the AI writer. Implementations must raise
        `domain.exceptions.InvalidSourceError` when extraction fails
        (broken link, private video, unreadable file, etc).
        """
        raise NotImplementedError
