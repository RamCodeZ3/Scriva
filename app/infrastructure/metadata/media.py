import json
import subprocess

from domain.value_objects.bib_metadata import BibMetadata

from infrastructure.metadata.common import TIMEOUT, put, set_date


def read_audio(meta: BibMetadata, path: str) -> None:
    from mutagen import File

    media = File(path, easy=True)
    if media is None:
        return
    for target, key in (("title", "title"), ("author", "artist")):
        values = media.get(key) or []
        put(meta, target, "; ".join(values) or None, "media_tags")
    dates = media.get("date") or []
    set_date(meta, dates[0] if dates else None, "media_tags")
    length = getattr(getattr(media, "info", None), "length", None)
    if length is not None and length >= 0:
        put(meta, "duration_seconds", int(length), "media_tags")


def read_ffprobe(meta: BibMetadata, path: str) -> None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=True,
    )
    info = json.loads(result.stdout).get("format", {})
    tags = {key.lower(): value for key, value in info.get("tags", {}).items()}
    put(meta, "title", tags.get("title"), "media_tags")
    put(meta, "author", tags.get("artist"), "media_tags")
    set_date(meta, tags.get("date") or tags.get("creation_time"), "media_tags")
    try:
        duration = int(float(info["duration"]))
        if duration >= 0:
            put(meta, "duration_seconds", duration, "media_tags")
    except (KeyError, ValueError, TypeError, OverflowError):
        pass
