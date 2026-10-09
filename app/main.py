from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

import uvicorn
from api.deps import get_document_process_repository
from api.v1.documents import router as documents_router
from api.v1.google_credentials import router as google_credentials_router
from api.v1.sources import router as sources_router
from application.exceptions import (
    ApplicationError,
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    NoSourcesExtractedError,
    SourceAccessDeniedError,
    SourceNotFoundError,
    UnsupportedSourceTypeError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from application.ports.document_exporter_resolver_port import (
    UnsupportedExportTargetError,
)
from domain.exceptions import (
    ActiveDocumentProcessError,
    DocumentBuildError,
    InvalidSourceError,
)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(_stale_process_sweep(stop))
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _stale_process_sweep(stop: asyncio.Event) -> None:
    interval = float(os.environ.get("PROCESS_SWEEP_INTERVAL_SECONDS", "60"))
    max_age = int(os.environ.get("PROCESS_STALE_AFTER_SECONDS", "900"))
    while not stop.is_set():
        try:
            repository = get_document_process_repository()
            await repository.fail_stale(timedelta(seconds=max_age))
        except Exception:
            logger.exception("Failed to sweep stale document processes.")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue


app = FastAPI(title="APA Document Generator API", lifespan=lifespan)

origins = [
    "http://localhost",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(sources_router)
app.include_router(google_credentials_router)


@app.exception_handler(ActiveDocumentProcessError)
async def active_document_process_handler(
    request: Request, exc: ActiveDocumentProcessError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(UserNotFoundError)
async def user_not_found_handler(
    request: Request, exc: UserNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(DocumentNotFoundError)
async def document_not_found_handler(
    request: Request, exc: DocumentNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SourceNotFoundError)
async def source_not_found_handler(
    request: Request, exc: SourceNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SourceAccessDeniedError)
async def source_access_denied_handler(
    request: Request, exc: SourceAccessDeniedError
) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(DocumentAccessDeniedError)
async def document_access_denied_handler(
    request: Request, exc: DocumentAccessDeniedError
) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(DocumentBuildError)
async def document_build_error_handler(
    request: Request, exc: DocumentBuildError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(InvalidSourceError)
async def invalid_source_error_handler(
    request: Request, exc: InvalidSourceError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(UnsupportedExportTargetError)
async def unsupported_export_target_handler(
    request: Request, exc: UnsupportedExportTargetError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(UnsupportedSourceTypeError)
async def unsupported_source_type_handler(
    request: Request, exc: UnsupportedSourceTypeError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(UserAlreadyExistsError)
async def user_already_exists_handler(
    request: Request, exc: UserAlreadyExistsError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ApplicationError)
async def application_error_handler(
    request: Request, exc: ApplicationError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(NoSourcesExtractedError)
async def no_sources_extracted_handler(
    request: Request, exc: NoSourcesExtractedError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
