# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# ffmpeg -> required by openai-whisper to process audio/video
# curl/ca-certificates -> required by the Playwright installer
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv: the dependency manager this project uses (pyproject.toml + uv.lock)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 1) Copy only the manifests first: if the source code changes but the
#    dependencies don't, Docker reuses this layer and skips reinstalling.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 2) Playwright: download Chromium plus every system library it needs
#    to render JavaScript-heavy pages.
RUN uv run playwright install --with-deps chromium

# 3) Now copy the rest of the source code.
COPY . .
RUN uv sync --frozen --no-dev

# 4) (Optional but recommended) warm up the Whisper base model at build
#    time, so the first request doesn't pay for that ~150 MB download.
#    Comment this out if you'd rather it download lazily at runtime.
RUN uv run python -c "import whisper; whisper.load_model('base')"

EXPOSE 8000

# ADJUST "app.main:app" to match the actual module where your FastAPI
# instance lives (search the project for `app = FastAPI(` to confirm it).
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
