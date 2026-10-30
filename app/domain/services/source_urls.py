"""Pure source URL identification shared by classification and adapters."""

import re
from urllib.parse import parse_qs, urlparse


def youtube_id(raw: str) -> str | None:
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }:
        parts = parsed.path.strip("/").split("/")
        candidate = (
            parse_qs(parsed.query).get("v", [""])[0]
            if parsed.path == "/watch"
            else parts[1]
            if len(parts) > 1 and parts[0] in {"shorts", "embed", "live"}
            else ""
        )
    else:
        return None
    return (
        candidate if re.fullmatch(r"[\w-]{11}", candidate, re.ASCII) else None
    )
