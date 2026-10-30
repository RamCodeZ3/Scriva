"""Inspect bibliographic metadata without downloading media."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from infrastructure.metadata.enricher import (
    MetadataEnricherAdapter,  # noqa: E402
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument(
        "--tipo",
        default="auto",
        choices=(
            "auto",
            "youtube",
            "web",
            "pdf",
            "docx",
            "pptx",
            "audio",
            "video",
            "text",
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON (also the default output format).",
    )
    args = parser.parse_args()
    enricher = MetadataEnricherAdapter(
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY"),
        crossref_email=os.environ.get("CROSSREF_CONTACT_EMAIL"),
    )
    meta = await enricher.enrich(args.source, args.tipo)
    print(json.dumps(meta.to_dict(), ensure_ascii=False, indent=2))
    return 0 if meta.title else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
