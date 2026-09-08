from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote
from uuid import UUID, uuid4

from application.dtos.document_dtos import (
    AugmentDocumentInput,
    CreateDocumentInput,
    DocumentFileOutput,
    DocumentOutput,
    ExportDocumentInput,
    UpdateDocumentInput,
)
from application.exceptions import UserNotFoundError
from application.use_cases.augment_document_use_case import (
    AugmentDocumentUseCase,
)
from application.use_cases.create_document_use_case import (
    CreateDocumentUseCase,
)
from application.use_cases.delete_document_use_case import (
    DeleteDocumentUseCase,
)
from application.use_cases.export_document_use_case import (
    ExportDocumentUseCase,
)
from application.use_cases.get_document_use_case import GetDocumentUseCase
from application.use_cases.list_user_documents_use_case import (
    ListUserDocumentsUseCase,
)
from application.use_cases.update_document_use_case import (
    UpdateDocumentUseCase,
)
from domain.entities.user import User
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from api.deps import (
    get_augment_document_use_case,
    get_create_document_use_case,
    get_current_user,
    get_delete_document_use_case,
    get_export_document_use_case,
    get_get_document_use_case,
    get_list_user_documents_use_case,
    get_update_document_use_case,
)
from api.schemas.documents import (
    AugmentDocumentRequest,
    CreateDocumentRequest,
    DeleteDocumentResponse,
    DocumentMetadataResponse,
    DocumentReferenceResponse,
    ExportDocumentResponse,
)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _request_body_openapi(schema_name: str) -> dict:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["payload"],
                        "properties": {
                            "payload": {"type": "string", "format": "json"},
                            "files": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "format": "binary",
                                },
                            },
                        },
                    }
                },
            },
        }
    }


@router.post(
    "/",
    response_class=StreamingResponse,
    openapi_extra=_request_body_openapi("CreateDocumentRequest"),
    responses={
        200: {
            "description": (
                "Progressive JSON metadata followed by the generated DOCX."
            ),
            "content": {"multipart/mixed": {}},
        }
    },
)
async def create_document(
    request: Request,
    current_user: User = Depends(get_current_user),
    use_case: CreateDocumentUseCase = Depends(get_create_document_use_case),
) -> StreamingResponse:
    body, cleanup = await _request_with_files(request, CreateDocumentRequest)
    try:
        document_type = DocumentType(body.document_type)
        presentation = PresentationInfo(
            student_name=body.user,
            professor=body.professor,
            subject=body.subject,
            student_id=body.student_id,
            institution=body.institution,
        )
    except ValueError as exc:
        cleanup()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    data = CreateDocumentInput(
        user_id=current_user.id,
        title=_title_snippet(body),
        document_type=document_type,
        presentation=presentation,
        sources=body.sources,
        additional_notes=body.additional_notes,
    )

    return _progressive_document_response(
        lambda on_progress: use_case.execute(data, on_progress),
        cleanup=cleanup,
    )


@router.post(
    "/{document_id}/export/{type_export}",
    response_model=ExportDocumentResponse,
)
async def export_document(
    document_id: UUID,
    type_export: str,
    current_user: User = Depends(get_current_user),
    use_case: ExportDocumentUseCase = Depends(get_export_document_use_case),
) -> ExportDocumentResponse:
    try:
        pass
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid document_id '{document_id}': {exc}",
        ) from exc

    data = ExportDocumentInput(
        document_id=document_id, user_id=current_user.id, export=type_export
    )
    result = await use_case.execute(data)

    return ExportDocumentResponse(
        status="exported",
        document_id=str(document_id),
        export=type_export,
        url=result.url,
        file_base64=(
            base64.b64encode(result.file_bytes).decode("ascii")
            if result.file_bytes
            else None
        ),
        file_name=result.file_name,
        content_type=result.content_type,
    )


@router.get(
    "/{document_id}",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {DOCX_MEDIA_TYPE: {}},
            "headers": {
                "X-Document-Metadata": {
                    "schema": {"type": "string"},
                    "description": "JSON matching DocumentMetadataResponse.",
                }
            },
        }
    },
)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    use_case: GetDocumentUseCase = Depends(get_get_document_use_case),
) -> StreamingResponse:
    result = await use_case.execute(document_id, current_user.id)

    return _docx_response(result)


@router.patch(
    "/ai/{document_id}",
    response_class=StreamingResponse,
    openapi_extra=_request_body_openapi("AugmentDocumentRequest"),
    responses={
        200: {
            "description": (
                "Progressive JSON metadata followed by the updated DOCX."
            ),
            "content": {"multipart/mixed": {}},
        }
    },
)
async def augment_document(
    document_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    use_case: AugmentDocumentUseCase = Depends(get_augment_document_use_case),
) -> StreamingResponse:
    body, cleanup = await _request_with_files(request, AugmentDocumentRequest)
    data = AugmentDocumentInput(
        document_id=document_id,
        user_id=current_user.id,
        sources=body.sources,
        additional_notes=body.additional_notes,
    )
    return _progressive_document_response(
        lambda on_progress: use_case.execute(data, on_progress),
        cleanup=cleanup,
    )


@router.patch(
    "/{document_id}",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "The parsed, persisted, and rebuilt DOCX.",
            "content": {DOCX_MEDIA_TYPE: {}},
        }
    },
)
async def update_document(
    document_id: UUID,
    title: str | None = Form(default=None),
    document: UploadFile | None = File(default=None),
    current_user: User = Depends(get_current_user),
    use_case: UpdateDocumentUseCase = Depends(get_update_document_use_case),
) -> StreamingResponse:
    if title is None and document is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least 'title' or a DOCX file.",
        )
    docx_bytes = None
    if document is not None:
        if not (document.filename or "").lower().endswith(".docx"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only .docx files are accepted.",
            )
        docx_bytes = await document.read()

    data = UpdateDocumentInput(
        document_id=document_id,
        user_id=current_user.id,
        title=title,
        docx_bytes=docx_bytes,
    )
    result = await use_case.execute(data)

    return _docx_response(result)


@router.get("/list/{user_id}", response_model=list[DocumentReferenceResponse])
async def get_list_by_user_id(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    use_case: ListUserDocumentsUseCase = Depends(
        get_list_user_documents_use_case
    ),
) -> list[DocumentReferenceResponse]:
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You cannot access other users' documents.",
        )

    try:
        results = await use_case.execute(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return [
        DocumentReferenceResponse(
            id=str(doc.id),
            title=doc.title,
            updated_at=doc.updated_at.isoformat(),
        )
        for doc in results
    ]


@router.delete("/{document_id}", response_model=DeleteDocumentResponse)
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    use_case: DeleteDocumentUseCase = Depends(get_delete_document_use_case),
) -> DeleteDocumentResponse:
    await use_case.execute(document_id, current_user.id)
    return DeleteDocumentResponse(
        status="deleted", document_id=str(document_id)
    )


def _title_snippet(body: CreateDocumentRequest) -> str:
    if body.subject:
        return body.subject[:80]
    first = next((s.strip() for s in body.sources if s.strip()), "documento")
    return first.splitlines()[0][:80]


def _metadata_out(document: DocumentOutput) -> DocumentMetadataResponse:
    return DocumentMetadataResponse(
        id=str(document.id),
        title=document.title,
        document_type=document.document_type.value,
        status=document.status.value,
        user_id=str(document.user_id),
        error_message=document.error_message,
        error_stage=document.error_stage,
        sources_errors=[
            {"source_id": str(item.source_id), "error": item.error}
            for item in document.source_errors
        ]
        or None,
        source_ids=[str(source_id) for source_id in document.source_ids],
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
    )


def _docx_response(result) -> StreamingResponse:
    metadata = _metadata_out(result.document)
    disposition = f"attachment; filename*=UTF-8''{quote(result.file_name)}"
    return StreamingResponse(
        BytesIO(result.file_bytes),
        media_type=result.content_type,
        headers={
            "Content-Disposition": disposition,
            "X-Document-Metadata": json.dumps(
                metadata.model_dump(mode="json"), ensure_ascii=True
            ),
            "Access-Control-Expose-Headers": (
                "Content-Disposition, X-Document-Metadata"
            ),
        },
    )


def _progressive_document_response(
    operation: Callable[
        [Callable[[DocumentOutput], Awaitable[None]]],
        Awaitable[DocumentFileOutput],
    ],
    cleanup: Callable[[], None] | None = None,
) -> StreamingResponse:
    boundary = "scriva-document-stream"

    async def stream() -> AsyncIterator[bytes]:
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        async def report(metadata: DocumentOutput) -> None:
            await queue.put(("metadata", metadata))

        async def run() -> None:
            try:
                await queue.put(("result", await operation(report)))
            except Exception as exc:
                await queue.put(("error", exc))

        task = asyncio.create_task(run())
        last_metadata: DocumentMetadataResponse | None = None
        try:
            while True:
                item_type, item = await queue.get()
                if item_type == "metadata":
                    last_metadata = _metadata_out(item)
                    yield _json_part(boundary, last_metadata)
                    continue
                if item_type == "error":
                    if (
                        last_metadata is None
                        or last_metadata.status != "failed"
                    ):
                        failed = DocumentMetadataResponse(
                            status="failed",
                            error_message=str(item),
                            error_stage="internal",
                        )
                        yield _json_part(boundary, failed)
                    break

                result = item
                yield _file_part(boundary, result)
                break
            yield f"--{boundary}--\r\n".encode()
        finally:
            if not task.done():
                task.cancel()
            if cleanup is not None:
                await asyncio.to_thread(cleanup)

    return StreamingResponse(
        stream(),
        media_type=f'multipart/mixed; boundary="{boundary}"',
        headers={"X-Accel-Buffering": "no"},
    )


async def _request_with_files[RequestModel: BaseModel](
    request: Request,
    model: type[RequestModel],
) -> tuple[RequestModel, Callable[[], None]]:
    content_type = request.headers.get("content-type", "").lower()
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    try:
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            payload = form.get("payload")
            if not isinstance(payload, str):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        "Multipart requests require a 'payload' field "
                        "containing the JSON request."
                    ),
                )
            raw_data = json.loads(payload)
            if not isinstance(raw_data, dict):
                raise ValueError(
                    "The multipart payload must be a JSON object."
                )

            uploads = [
                item
                for item in form.getlist("files")
                if isinstance(item, StarletteUploadFile)
            ]
            if uploads:
                temporary_directory = tempfile.TemporaryDirectory(
                    prefix="scriva-sources-",
                    dir=_temporary_upload_root(),
                )
                paths = await _copy_uploads(
                    uploads, Path(temporary_directory.name)
                )
                raw_data["sources"] = [
                    *(raw_data.get("sources") or []),
                    *paths,
                ]
        elif content_type.startswith("application/json"):
            raw_data = await request.json()
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    "Use application/json or multipart/form-data with "
                    "'payload' and 'files' fields."
                ),
            )

        parsed = model.model_validate(raw_data)
    except json.JSONDecodeError as exc:
        if temporary_directory is not None:
            temporary_directory.cleanup()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid JSON payload: {exc.msg}.",
        ) from exc
    except (TypeError, ValueError, ValidationError) as exc:
        if temporary_directory is not None:
            temporary_directory.cleanup()
        detail = (
            exc.errors(include_context=False)
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail,
        ) from exc
    except Exception:
        if temporary_directory is not None:
            temporary_directory.cleanup()
        raise

    cleanup = (
        temporary_directory.cleanup
        if temporary_directory is not None
        else lambda: None
    )
    return parsed, cleanup


def _temporary_upload_root() -> str | None:
    memory_directory = "/dev/shm"
    if os.path.isdir(memory_directory) and os.access(
        memory_directory, os.W_OK
    ):
        return memory_directory
    return None


async def _copy_uploads(
    uploads: list[StarletteUploadFile], destination: Path
) -> list[str]:
    paths: list[str] = []
    for upload in uploads:
        suffix = Path(upload.filename or "").suffix.lower()
        path = destination / f"{uuid4()}{suffix}"
        await asyncio.to_thread(_copy_file, upload.file, path)
        await upload.close()
        paths.append(str(path))
    return paths


def _copy_file(source: BinaryIO, destination: Path) -> None:
    source.seek(0)
    with destination.open("wb") as output:
        shutil.copyfileobj(source, output)


def _json_part(boundary: str, metadata: DocumentMetadataResponse) -> bytes:
    payload = json.dumps(
        metadata.model_dump(mode="json"), ensure_ascii=True
    ).encode()
    return (
        f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode()
        + payload
        + b"\r\n"
    )


def _file_part(boundary: str, result: DocumentFileOutput) -> bytes:
    disposition = f"attachment; filename*=UTF-8''{quote(result.file_name)}"
    return (
        f"--{boundary}\r\nContent-Type: {result.content_type}\r\n"
        f"Content-Disposition: {disposition}\r\n\r\n".encode()
        + result.file_bytes
        + b"\r\n"
    )
