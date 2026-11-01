# Scriva

An intelligent service that ingests one or more information sources — web pages, YouTube videos, plain text, or uploaded files — and uses AI to automatically draft a complete, publication-ready document (title page, table of contents, introduction, body, conclusion, and references) formatted according to **APA 7th edition**.

The goal is to extract information from virtually any source and automatically
produce a report, documentary research paper, summary, synthesis, or executive
brief. Each type has its own source-grounded section blueprint while sharing
the same document node model and export pipeline.

## Purpose

Turn raw, unstructured source material into a fully structured, properly cited document with minimal manual effort. The service handles extraction, AI-driven drafting, APA 7 formatting, and export — end to end.

## Target Audience

| Audience | Primary Use Case |
|---|---|
| **Students & Researchers** | Convert dense readings, papers, or recorded lectures into APA-formatted monographs or study cards. |
| **Teachers & Educators** | Transform videos or readings into quizzes, exams, and topic guides for students. |
| **Consultants & Analysts** | Ingest industry reports or webinars to generate client-ready executive reports. |
| **Content Creators** | Structure in-depth research into formal documents before scripting or writing. |

## Control Flow

1. **Request submission** — The client (web app) sends a request containing the source(s) or media to extract information from.
2. **Source analysis & extraction** — The system detects the source type (YouTube link, web page, uploaded file, etc.) and extracts its content, converting it into clean, AI-processable text.
3. **AI drafting** — The extracted text is passed to the AI along with a structured prompt; the AI drafts the document content (presentation, table of contents, body, introduction, conclusion, sources) following APA 7 guidelines.
4. **Export** — If the user chooses to export, the finished document content is generated and delivered in the requested output format.

## Tech Stack

- **Python** — Core language integrating the APIs, orchestrating the asynchronous data flow, and running the pipeline logic.
- **Gemini API** — Processes extracted sources and automatically drafts the structured document content (presentation, table of contents, body, etc.) under APA 7 rules.
- **FastAPI** — Exposes the REST API endpoints for receiving document-generation requests and managing backend processing state.
- **Playwright** — Extracts text and relevant content from web pages, including dynamic, JavaScript-rendered sites.
- **Google Drive API** — Converts the generated DOCX into a native Google
  Docs document in the user's Drive.
- **Supabase** — Stores the user database, source metadata, and processing status records.
- **DiskCache** — Stores compiled DOCX binaries on local disk with content-addressed keys and LRU eviction.
- **reportlab** — Generates PDF output for the final documents.
- **ODFpy** — Generates editable ODT output with document formatting and
  navigation preserved.
- **youtube-transcript-api** — Retrieves transcripts from YouTube videos as a source input.
- **OpenAI Whisper** — Transcribes local audio and video files supported by FFmpeg.

Whisper uses the multilingual `base` model by default. Set `WHISPER_MODEL` to
another installed model name or `WHISPER_DEVICE` to `cpu` or `cuda` when an
explicit runtime device is required. FFmpeg must be available on `PATH`.

Google Docs export requires the OAuth scope
`https://www.googleapis.com/auth/drive.file`. The client that starts the
Google authorization flow must request offline access and explicit consent
with this scope. Refresh tokens issued before this scope was added must be
re-authorized; the export endpoint reports this requirement when Drive
returns HTTP 403.

Document creation and AI augmentation continue to accept their existing JSON
bodies. To include local files, send `multipart/form-data` with `payload`
containing that same JSON object and repeat the `files` field for every
upload. `sources` may be empty when at least one file is present, and files
may be omitted when `sources` contains at least one item. Uploaded files
exist only in an isolated temporary directory while the
document stream is running. Linux uses memory-backed `/dev/shm` when
available; other environments use their system temporary directory. Files are
removed when the stream finishes or is cancelled.

## Supported Output Formats

- Summary
- Synthesis
- Report
- Executive report
- Study guide
- Quiz / Exam

## Progressive Document Responses

`POST /api/v1/documents/` and
`PATCH /api/v1/documents/ai/{document_id}` return `multipart/mixed` streams.
Each stream contains progressive `application/json` metadata parts followed,
after the `done` event, by the generated DOCX part. Creation reports
`extracting`, `generating`, `drafting`, and `done`; AI augmentation reports
`extracting`, `expanding`, `drafting`, and `done`.

Creation uses `CreateDocumentResponse`, which includes `source_ids` and error
details. Retrieval, manual updates, and AI augmentation use
`DocumentMetadataResponse`, which omits `source_ids`, `error_message`,
`error_stage`, and `sources_errors`. Retrieval and manual updates send these
metadata in the `X-Document-Metadata` header alongside the DOCX body.

During creation, failed sources appear in `sources_errors` without stopping processing when at
least one source succeeded. A fatal error ends the stream with `status` set to
`failed`, its cause in `error_message`, and the failing pipeline stage in
`error_stage`. AI augmentation reports fatal errors with `status="failed"`
without error details. No DOCX part follows a fatal error event.

## Gemini model fallback

Generation and expansion try Gemini models sequentially, stopping at the first
valid document. The default priority favors capability: Gemini 3.8 Flash,
3.6 Flash, 3.5 Flash-Lite, then 3.1 Flash-Lite. These text models have free
input/output tiers in the [official pricing documentation](https://ai.google.dev/gemini-api/docs/pricing)
(checked October 24, 2026). Availability and quotas depend on the project;
a paid project can still incur charges for these models.

```env
GEMINI_API_KEY=
GEMINI_MODELS=gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite
GEMINI_MAX_INPUT_TOKENS=1000000
AI_ATTEMPT_TIMEOUT_SECONDS=120
AI_TOTAL_BUDGET_SECONDS=480
AI_CIRCUIT_COOLDOWN_SECONDS=60
```

`GEMINI_MODELS` is an ordered, comma-separated list; blank entries and duplicate
models are removed. An empty list is rejected. `GEMINI_MODELS` is the only
model-order configuration; the legacy `GEMINI_MODEL` variable is ignored.
Restart the backend after changing the list to reload the cached writer.
Groq configuration and `AI_PROVIDER_ORDER` are no longer used.
`GEMINI_API_KEY` is required. The context limit applies to each model.

The next model is attempted after rate limits, authentication errors, timeouts,
network/5xx errors, invalid JSON, or document validation failures. Each model
is attempted at most once per request, within the attempt timeout and total
budget. If all fail or the budget expires, processing fails with attempt
history; it does not retry indefinitely. Empty source input does not trigger
fallback. A model returning 429 or 5xx is temporarily skipped by an in-memory
circuit breaker keyed by provider and model, so other Gemini models remain
available. Circuit state is local to each application process. Document content
and API keys are never written to fallback logs. Attempt metadata stays private.

## Documents and process history

Stable document content belongs to `documents`: ownership, type, title,
accumulated sources, and the canonical node tree. Runtime state belongs to the
1:N `document_process_details` history. Every generation or expansion creates
a process; API status, errors, and guards are derived from the newest process.
Only one active process is allowed per document.

Each process stores the sources handled by that execution and private AI
metadata (`ai_provider`, `ai_model_used`, and `ai_attempts`). This metadata is
not exposed through API responses. Failed source details remain derived from
the related `Source` records.

Because current status is the latest process, a failed expansion currently
makes the document appear failed even though its previous content remains
stored. Restoring the last successful process as the visible state is a future
improvement.

Interrupted requests are marked failed, and an idempotent periodic sweep
closes stale active processes. Configure it with
`PROCESS_SWEEP_INTERVAL_SECONDS` and `PROCESS_STALE_AFTER_SECONDS`; the stale
threshold must exceed the total AI budget plus expected extraction time.

### Migration deployment order

1. Apply the expand migration `202610090001`.
2. Deploy the process-aware application code and verify generation, expansion,
   reads, exports, and stale-process handling.
3. Take a database backup and obtain explicit human confirmation.
4. Apply the destructive contract migration `202610090002`.
5. Deploy code that no longer relies on the legacy document columns.

Never apply the contract migration before the process-aware code is stable.
Conversely, code that assumes the legacy columns are absent must not be
deployed before the contract migration is ready and coordinated.

## Bibliographic metadata

Extractors enrich sources with verified bibliographic metadata and field-level
provenance. YouTube metadata uses yt-dlp with oEmbed and optional Data API
fallbacks; transcription continues to use youtube-transcript-api. Web, PDF,
Office, local media, and text sources share the same contract. See the
[implementation report and CLI guide](docs/bibliographic-metadata.md) for
configuration, persistence, review flags, validation, and remaining limits.

## Status

This project is under active development. issues, and feedback are welcome.
