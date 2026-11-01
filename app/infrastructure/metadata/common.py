from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from domain.services.source_urls import youtube_id as youtube_id
from domain.value_objects.bib_metadata import BibMetadata, Origin

logger = logging.getLogger(__name__)
TIMEOUT = 10


def clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def put(meta: BibMetadata, field: str, value: Any, origin: Origin) -> None:
    if field in {"published_year", "duration_seconds"}:
        if isinstance(value, bool) or not isinstance(value, int):
            return
        if field == "published_year" and not 1 <= value <= 9999:
            return
        if field == "duration_seconds" and value < 0:
            return
    elif field == "published_at":
        if not isinstance(value, date):
            return
    else:
        value = clean(value)
    if value is not None and getattr(meta, field) is None:
        setattr(meta, field, value)
        meta.origins[field] = origin


def set_date(meta: BibMetadata, value: object, origin: Origin) -> None:
    if meta.published_at or meta.published_year:
        return
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        parsed = value
    else:
        text = clean(value)
        if not text:
            return
        if re.fullmatch(r"\d{4}", text):
            year = int(text)
            if 1 <= year <= 9999:
                put(meta, "published_year", year, origin)
            return
        try:
            if re.fullmatch(r"\d{8}", text):
                parsed = datetime.strptime(text, "%Y%m%d").date()
            else:
                parsed = datetime.fromisoformat(
                    text.replace("Z", "+00:00").replace("/", "-")
                ).date()
        except ValueError:
            # Partial dates must never acquire an invented day or month.
            if re.fullmatch(r"\d{4}-\d{2}", text):
                try:
                    datetime.strptime(text, "%Y-%m")
                except ValueError:
                    return
                put(meta, "published_year", int(text[:4]), origin)
            return
    put(meta, "published_at", parsed, origin)
    put(meta, "published_year", parsed.year, origin)


def timestamp_date(value: object) -> date | None:
    try:
        return datetime.fromtimestamp(float(value), UTC).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def normalize_title(meta: BibMetadata) -> None:
    title = clean(meta.title)
    if title:
        for suffix in (" - YouTube", f" | {meta.site_name}"):
            if title.casefold().endswith(suffix.casefold()):
                title = title[: -len(suffix)].strip()
        meta.title = title or None


def file_title(meta: BibMetadata, path: str) -> None:
    if not meta.title:
        put(meta, "title", Path(path).stem, "ninguno")
        meta.needs_review = True
