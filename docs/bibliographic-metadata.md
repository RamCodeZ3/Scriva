# Bibliographic enrichment implementation report

## Behavior and architecture

Text extraction and bibliographic enrichment are separate operations. No LLM
is called by the enrichment module, and missing values remain null. Metadata
failures do not invalidate successfully extracted text. Content extraction
errors still mark a source failed through the existing processing workflow.

`MetadataEnricherPort` and the re-exported `BibMetadata` contract live in
`application/ports/bib_metadata_port.py`. The framework-independent value object
lives in the domain so that `Source` can retain it without depending on the
application layer. Provider implementations live in `infrastructure/metadata`.
The API composition root shares one enricher among the registered extractors.

The contract retains title, author, full date, year, site, URL, DOI, publisher,
duration, field provenance, and a review flag. Only an actual complete date
populates `published_at`. A year or a year-month value populates
`published_year`, without fabricating January 1. Non-string provider titles
and authors are ignored. Whitespace and known site suffixes are cleaned.

`origins` covers populated bibliographic fields; `source_type` and
`needs_review` are structural flags. To retain the requested origin vocabulary,
`ninguno` denotes a value from the input URL, a filename fallback, or a date
heuristic. Filename and heuristic values always require review. Provider
origins are otherwise recorded field by field.

## Provider behavior

| Source | Retrieval and fallback behavior |
| --- | --- |
| YouTube | yt-dlp metadata only; then oEmbed for missing title/channel; then Data API v3, when configured, for missing fields including the date. Existing values survive fallbacks. |
| Web | Existing HTML meta tags, JSON-LD article objects and `@graph`, Highwire/Dublin Core, document title, then htmldate for a missing date. DOI triggers Crossref. Rendered HTML is reused from Playwright. |
| PDF | DOI lookup in the first two pages; Crossref overrides fields it supplies. Internal title/author/creation date remain as fallbacks, then the filename. |
| DOCX/PPTX | Core properties, rejecting generic/system authors; creation date with modified date as fallback. Always requires review. |
| Local audio | Mutagen title, artist, date, duration; ffprobe fills gaps. Always requires review. |
| Local video | ffprobe tags and duration, then filename. Always requires review. |
| TXT file | Filename title with review required. |
| Plain text | Empty metadata with review required. |

JSON-LD is parsed with the existing Beautiful Soup dependency and Python's JSON
parser; an additional extruct dependency is unnecessary for these fields.
Crossref authors are normalized only from separate family/given fields; all
authors are retained, separated by semicolons. Channel and organization names
are retained verbatim. PDF DOI extraction preserves balanced parentheses.

YouTube transcription **still uses youtube-transcript-api**. yt-dlp uses
`skip_download=True` and `extract_info(..., download=False)` and never downloads
video or audio. URL identification is shared with domain source classification;
short links, watch query parameters in any order, Shorts, embeds and live URLs
are supported. Lookalike domains are rejected.

HTTP calls have a ten-second timeout and an overall ten-second request await.
yt-dlp sockets use ten seconds, retries are disabled, and its await has a
ten-second limit. Blocking SDK/file work runs in worker threads. A timed-out
yt-dlp worker can finish its current socket operation in the background; it
cannot mutate returned metadata. ffprobe has a ten-second subprocess timeout.
Web content extraction retains its existing configurable navigation timeout;
standalone metadata navigation uses ten seconds.

Successful HTTP JSON responses are cached by URL/query, including DOI lookups.
Complete YouTube metadata is cached by normalized video ID. Both caches are
instance-local, limited to 256 entries with a one-hour lifetime, and return
independent copies. Incomplete YouTube results and HTTP failures are retried on
later requests. No distributed cache or automatic refresh job is introduced.

## Persistence, API and references

The existing `sources.metadata` JSON stores the complete contract in
`bibliographic`, alongside the existing citation fields and the new
`published_year`. No database migration is required. Older rows without these
keys still load. Partial extraction retries retain earlier populated metadata.
Generation and augmentation both persist enriched results.

Source list and detail responses add a nullable `bibliographic` object without
removing existing fields. Existing authentication and ownership checks remain
in effect. Uploaded files retain their original basename in a unique temporary
directory; this avoids UUID reference titles, collisions, and path traversal.

The citation service remains responsible for references. Its changes are
limited to year-only dates and preserving enriched author names instead of
applying the previous word-count abbreviation heuristic. Crossref in-text
citations use the supplied surnames. Existing sources without the new contract
retain legacy author formatting. References still include only cited sources.
DOI, publisher, and duration are retained in source metadata; no new reference
rendering templates were added to consume those extra fields.

Example with mocked verified video data:

```text
Science Channel. (2024, enero 2). Actual title [Video]. YouTube.
https://www.youtube.com/watch?v=abcdefghijk
```

## Setup and CLI

Install the locked dependencies with `uv sync`. New direct dependencies are
`yt-dlp`, `htmldate`, `pypdf`, `mutagen`, and `httpx`; python-docx and python-pptx
were already present. FFmpeg supplies ffprobe. Standalone web metadata also
requires the Playwright Chromium browser used by the application.

Optional environment variables:

- `YOUTUBE_API_KEY`: enables the final YouTube Data API fallback.
- `CROSSREF_CONTACT_EMAIL`: adds the operator's real contact email to the
  Crossref User-Agent. Configure it to use the polite pool; no email is invented.

```bash
uv run python scripts/extraer_metadatos.py 'https://youtu.be/VIDEO_ID' --json
uv run python scripts/extraer_metadatos.py ./paper.pdf --tipo pdf --json
uv run python scripts/extraer_metadatos.py ./notes.txt --json
```

Supported explicit types: auto, youtube, web, pdf, docx, pptx, audio, video, text.
The script prints JSON, including provenance and review status, and exits zero
when a title is available or one otherwise. Environment variables configure
optional integrations; the CLI does not load a local environment file itself.

YouTube changes frequently. The minimum dependency is `yt-dlp>=2026.10.14`.
For project upgrades use `uv lock --upgrade-package yt-dlp` and `uv sync`.
For a separately managed pip environment, use `pip install -U yt-dlp`.

## Validation and limits

All 173 tests pass, including 26 new metadata tests. CLI smoke checks confirm
exit zero for a TXT filename title and exit one for plain text without a title.

The new tests mock yt-dlp, oEmbed, YouTube Data API, Crossref, PDF metadata,
Mutagen, ffprobe and HTTP caching. Local DOCX/PPTX fixtures exercise actual
property readers. Tests also cover year precision, malformed provider data,
web metadata priorities, review flags, independent transcription, persistence,
partial retries, API serialization, upload names, and the resulting reference.

Validation commands:

```bash
uv run ruff format .
uv run ruff check .
PYTHONPATH=app uv run python -m unittest discover -s tests -q
```

The repository-wide Ruff check reports 15 pre-existing findings in unrelated
files. A comparison against the original HEAD confirmed the same findings and
rule counts; changed and new files pass lint. Formatting passes repository-wide.

Live public-video availability, IP/age restrictions and external service
uptime are not guaranteed by unit tests. No live service credentials or
production database were used. Missing metadata remains available for review;
there is no historical backfill. This backend exposes `needs_review` and
provenance but contains no frontend review screen or metadata correction
endpoint. A frontend review workflow must be implemented separately before it
can block generation for user correction.

References for provider behavior:

- [yt-dlp Python embedding](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp)
- [Crossref access and contact headers](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)
