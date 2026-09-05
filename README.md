# Scriva

An intelligent service that ingests one or more information sources — web pages, YouTube videos, plain text, or uploaded files — and uses AI to automatically draft a complete, publication-ready document (title page, table of contents, introduction, body, conclusion, and references) formatted according to **APA 7th edition**.

The goal is to extract information from virtually any source and automatically produce a document in the requested format: summary, synthesis, report, executive brief, study guide, quiz, and more.

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
- **Google Docs API** — Creates, formats, and exports the final document with the requested layout and styling.
- **Supabase** — Stores the user database, source metadata, and processing status records.
- **DiskCache** — Stores compiled DOCX binaries on local disk with content-addressed keys and LRU eviction.
- **reportlab** — Generates PDF output for the final documents.
- **youtube-transcript-api** — Retrieves transcripts from YouTube videos as a source input.
- **OpenAI Whisper** — Transcribes local audio and video files supported by FFmpeg.

Whisper uses the multilingual `base` model by default. Set `WHISPER_MODEL` to
another installed model name or `WHISPER_DEVICE` to `cpu` or `cuda` when an
explicit runtime device is required. FFmpeg must be available on `PATH`.

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

Failed sources appear in `sources_errors` without stopping processing when at
least one source succeeded. A fatal error ends the stream with `status` set to
`failed`, its cause in `error_message`, and the failing pipeline stage in
`error_stage`; no DOCX part follows that event.

## Status

This project is under active development. issues, and feedback are welcome.
