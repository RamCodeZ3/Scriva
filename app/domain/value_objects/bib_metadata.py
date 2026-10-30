"""Verified bibliographic values and their field-level provenance."""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

Origin = Literal[
    "html_meta",
    "json_ld",
    "yt_dlp",
    "oembed",
    "youtube_api",
    "crossref",
    "doc_properties",
    "pdf_info",
    "media_tags",
    "ninguno",
]


@dataclass
class BibMetadata:
    source_type: str
    title: str | None = None
    author: str | None = None
    published_at: date | None = None
    published_year: int | None = None
    site_name: str | None = None
    url: str | None = None
    doi: str | None = None
    publisher: str | None = None
    duration_seconds: int | None = None
    origins: dict[str, Origin] = field(default_factory=dict)
    needs_review: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["published_at"] = (
            self.published_at.isoformat() if self.published_at else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "BibMetadata":
        values = {
            key: value
            for key, value in data.items()
            if key in cls.__dataclass_fields__
        }
        if values.get("published_at"):
            values["published_at"] = date.fromisoformat(values["published_at"])
        return cls(**values)
