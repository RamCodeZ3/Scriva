# Scriva Backend Agent Guide

## Project Mission

Scriva is the backend core of an AI-assisted document-generation service. It
accepts one or more information sources, including plain text, web pages,
YouTube videos, and uploaded files, extracts their useful content, and turns
that content into a complete document.

Generated documents may be summaries, syntheses, reports, executive briefs,
study guides, questionnaires, quizzes, or other requested document types. A
document can contain a title/presentation page, table of contents,
introduction, body, conclusion, and references. Content and formatting must
follow APA 7 requirements whenever they apply. Users must be able to retrieve,
edit, export, and extend an existing document with additional sources.

Preserve this end-to-end flow when making changes:

1. Receive and validate the authenticated API request.
2. Classify and persist the submitted sources.
3. Select the appropriate extractor for each source.
4. Pass successfully extracted text to the document writer.
5. Convert the AI's structured JSON output into domain document nodes.
6. Persist document state and source relationships.
7. Return or export the document in the requested format.

Failure of one source should not discard other successfully extracted sources
unless the use case cannot produce a valid document without it. Keep document
and source processing states consistent when failures occur.

## Architecture

The project follows hexagonal architecture. The dependency direction is:

`api -> application -> domain`

`infrastructure -> application/domain`

The inner layers must never depend on FastAPI, Supabase, Gemini, Playwright,
Google APIs, or another infrastructure implementation.

### Domain (`app/domain`)

This layer contains the business model and business rules:

- `entities/`: users, sources, and documents.
- `value_objects/`: document nodes, APA structure, document types,
  presentation information, and source references.
- `services/`: pure domain operations such as table-of-contents construction.
- `exceptions.py`: domain-specific failures.

Keep this layer framework-independent. Do not place HTTP schemas, database
rows, SDK clients, environment-variable access, or provider-specific logic
here. Enforce invariants in entities, value objects, or domain services rather
than duplicating them in routes and adapters.

### Application (`app/application`)

This layer coordinates business workflows:

- `use_cases/`: one class per application action, such as creating,
  processing, updating, augmenting, exporting, listing, or deleting a
  document.
- `ports/`: abstract contracts required by use cases.
- `dtos/`: input and output data passed across application boundaries.
- `exceptions.py`: application-level failures.

Use cases may depend on domain types and application ports, but not on concrete
adapters or web-framework types. Define or extend a port when a use case needs
an external capability. Keep orchestration in use cases and business rules in
the domain.

### Infrastructure (`app/infrastructure`)

This layer implements application ports with external technologies:

- `extractors/`: extract normalized text from plain text, uploaded files,
  websites, YouTube videos, audio, or other supported sources. Register new
  source implementations through the extractor factory.
- `ai/`: send extracted content to Gemini and map its structured JSON response
  to the domain document model.
- `export/`: render stored domain documents as DOCX, PDF, or Google Docs.
- `persistence/`: Supabase repositories and temporary/in-memory storage.
- `auth/`: Supabase JWT verification and Google OAuth token handling.
- `jobs/`: synchronous or background dispatch of document processing.
- `parsers/`: convert externally edited documents, currently DOCX, back into
  the internal document representation.

Adapters must implement application ports and translate provider-specific data
and errors at the boundary. Do not leak SDK response objects into the
application or domain. Keep extractor, persistence, AI, parser, and exporter
responsibilities separate.

Document content and processing state have separate persistence models.
`documents` owns stable content and ownership, while
`document_process_details` stores the 1:N history of generation and expansion
attempts. Derive public document status and errors from the newest process;
never reintroduce `status`, `error_message`, or `error_stage` as document-table
columns. Process-level AI provider/model/attempt metadata is private and must
not be exposed by API schemas.

### API (`app/api` and `app/main.py`)

This is the outermost layer and the composition root:

- `app/api/v1/`: versioned FastAPI routes.
- `app/api/schemas/`: request and response schemas.
- `app/api/deps.py`: dependency wiring, authentication, repositories,
  adapters, and use-case construction.
- `app/main.py`: FastAPI initialization, middleware, routers, and global
  exception-to-HTTP mappings.

Routes should validate and translate HTTP data, call one use case, and convert
the result into an HTTP response. Do not place business logic or direct
Supabase/Gemini calls in route handlers. Preserve ownership checks: an
authenticated user may access only their own documents.

## Technology Responsibilities

- Python 3.12+ is the implementation language and coordinates the asynchronous
  processing pipeline.
- FastAPI exposes the REST API and handles request/response boundaries.
- Gemini (`google-genai`) drafts structured document content from extracted
  sources. Treat model output as untrusted input: validate it before creating
  domain objects.
- Groq is the configured second writer through its OpenAI-compatible Chat
  Completions endpoint. Provider order, models, context limits, attempt timeout,
  total budget, and circuit-breaker cooldown are environment configuration.
  Circuit breakers are in-memory and local to an application instance.
- Playwright and Beautiful Soup extract relevant content from web pages,
  including JavaScript-rendered pages.
- `youtube-transcript-api` retrieves YouTube transcripts and metadata. The
  project does not currently use PyTube; do not introduce it without a concrete
  requirement.
- Google Docs API creates and formats Google Docs exports.
- Supabase stores users, documents, source metadata, credentials, and
  processing state.
- `python-docx` and ReportLab produce DOCX and PDF files respectively.

## Development Conventions

- Write all code, identifiers, comments, docstrings, API messages, and new
  documentation in English.
- Follow PEP 8 and the repository Ruff configuration in `ruff.toml`: Python
  3.12 syntax, a 79-character line limit, import sorting, and the enabled
  `E`, `W`, `F`, `I`, and `UP` rules.
- Prefer explicit type annotations on public functions, methods, DTO fields,
  ports, and adapter boundaries.
- Use `async` for I/O-bound workflows and preserve async behavior through the
  route, use-case, port, and adapter chain. Do not perform avoidable blocking
  network or file work in the event loop.
- Name abstract contracts with the `Port` suffix and concrete integrations with
  the `Adapter` suffix, matching the existing codebase.
- Keep provider configuration in the API composition root or infrastructure;
  access configuration through environment variables and never hard-code or
  commit secrets, access tokens, service-role keys, or credentials.
- Reuse domain entities and value objects instead of passing loose dictionaries
  through the core layers.
- Translate expected failures into domain or application exceptions, then map
  them to HTTP responses in `app/main.py`. Avoid broad exception swallowing.
- Preserve backward compatibility for public endpoints and persisted document
  JSON. If a contract must change, update schemas, DTOs, mappings, adapters,
  and documentation together.
- When adding a source type or export target, update its enum/model, relevant
  port, adapter, factory/resolver wiring in `app/api/deps.py`, error handling,
  and tests as one coherent change.

## Local Commands

Install and manage dependencies with `uv`.

```bash
uv sync
uv run app/main.py
uv run ruff format .
uv run ruff check .
```

Use `uv run ruff format --check .` when only verifying formatting. Before
finishing a code change, run at least `uv run ruff format .` and
`uv run ruff check .`, then run the relevant tests if a test suite exists for
the changed area. Add focused tests for new behavior under `tests/`.

The application expects environment variables for the integrations it wires,
including:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `SUPABASE_JWT_SECRET` (optional legacy verification)
- `GEMINI_API_KEY`
- `GOOGLE_TOKEN_ENCRYPTION_KEY`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `DOCX_CACHE_DIR` (optional; defaults to `./storage/cache/docx`)
- `DOCX_CACHE_SIZE_MB` (optional; defaults to `1024`)

Do not add real values to the repository.

## Change Checklist

Before considering a change complete:

1. Confirm the change belongs in the correct architectural layer.
2. Ensure dependency direction still points toward the domain.
3. Update all affected ports, adapters, dependency wiring, DTOs, and API
   schemas.
4. Verify document ownership, validation, error handling, and processing-state
   transitions.
5. Check that generated and exported content preserves the APA/document node
   structure.
6. Format and lint the repository and run relevant tests.
7. Update user-facing or architectural documentation when behavior changes.

## Git and Commit Conventions

Keep commits focused on one logical change. Do not mix unrelated formatting or
refactoring into a feature or bug fix. Use an imperative, concise Conventional
Commit subject with one of these prefixes:

- `feat:` for a new feature or externally visible behavior.
- `fix:` for a bug fix.
- `refactor:` for an internal restructuring that does not change behavior.
- `docs:` for documentation-only changes.

Examples:

```text
feat: add audio source extraction
fix: preserve references when augmenting a document
refactor: isolate Supabase document mapping
docs: document Google Docs export setup
```

Use the same prefixes for breaking changes, with `!` and a clear explanation
when appropriate, for example `feat!: change document creation response`.
Never commit secrets, generated exports, local environment files, or unrelated
user changes.
