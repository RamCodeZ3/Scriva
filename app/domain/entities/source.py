from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from urllib.parse import urlparse
from uuid import UUID, uuid4

from domain.exceptions import InvalidSourceError


class SourceType(Enum):
    WEB = "web"
    YOUTUBE = "youtube"
    FILE = "file"
    TEXT = "text"


class SourceStatus(Enum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    FAILED = "failed"


class FileKind(Enum):
    DOCUMENT = "document"
    VIDEO = "video"
    AUDIO = "audio"


_YOUTUBE_RE = re.compile(
    r"(youtube\.com/(watch\?v=|shorts/|embed/|live/)|youtu\.be/)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

_DOCUMENT_EXTS = {".pdf", ".docx", ".doc", ".txt", ".odt", ".rtf"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def classify_source(raw: str) -> tuple[SourceType, FileKind | None]:
    text = raw.strip()

    if _YOUTUBE_RE.search(text):
        return SourceType.YOUTUBE, None

    path = urlparse(text).path if _URL_RE.match(text) else text
    ext = os.path.splitext(path)[1].lower()

    if ext in _DOCUMENT_EXTS:
        return SourceType.FILE, FileKind.DOCUMENT
    if ext in _VIDEO_EXTS:
        return SourceType.FILE, FileKind.VIDEO
    if ext in _AUDIO_EXTS:
        return SourceType.FILE, FileKind.AUDIO

    if os.path.isfile(text):
        return SourceType.FILE, None

    if _URL_RE.match(text):
        return SourceType.WEB, None

    return SourceType.TEXT, None


@dataclass
class Source:
    id: UUID
    source_type: SourceType
    raw: str
    status: SourceStatus
    user_id: UUID | None = None
    file_kind: FileKind | None = None
    content: str | None = None
    char_count: int | None = None
    error_message: str | None = None
    created_at: datetime | None = None

    @classmethod
    def create(
        cls, raw: str, source_type: SourceType, user_id: UUID
    ) -> Source:
        return cls(
            id=uuid4(),
            source_type=source_type,
            raw=raw,
            status=SourceStatus.PENDING,
            user_id=user_id,
        )

    @classmethod
    def create_auto(cls, raw: str, user_id: UUID) -> Source:
        source_type, file_kind = classify_source(raw)
        return cls(
            id=uuid4(),
            source_type=source_type,
            raw=raw,
            status=SourceStatus.PENDING,
            user_id=user_id,
            file_kind=file_kind,
        )

    def mark_extracted(self, content: str) -> None:
        if not content.strip():
            raise InvalidSourceError("Extracted content cannot be empty.")
        self.content = content
        self.char_count = len(content)
        self.status = SourceStatus.EXTRACTED

    def mark_failed(self, reason: str) -> None:
        self.status = SourceStatus.FAILED
        self.error_message = reason

    def is_ready(self) -> bool:
        return self.status == SourceStatus.EXTRACTED

    def get_content(self) -> str:
        if not self.is_ready() or self.content is None:
            raise InvalidSourceError(
                "Source is not ready for use. Current status: "
                f"'{self.status.value}'."
            )
        return self.content
