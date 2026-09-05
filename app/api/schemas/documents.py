from __future__ import annotations

from pydantic import BaseModel, Field


class CreateDocumentRequest(BaseModel):
    user: str = Field(..., min_length=1)
    document_type: str
    sources: list[str] = Field(..., min_length=1)
    professor: str = Field(..., min_length=1)
    student_id: str = Field(..., min_length=1)
    institution: str = Field(..., min_length=1)
    subject: str | None = None
    additional_notes: str | None = None


class SourceError(BaseModel):
    source_id: str
    error: str


class DocumentMetadataResponse(BaseModel):
    id: str | None = None
    title: str | None = None
    document_type: str | None = None
    status: str
    user_id: str | None = None
    error_message: str | None = None
    sources_errors: list[SourceError] | None = None
    source_ids: list[str] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DocumentPatchResponse(BaseModel):
    id: str
    title: str
    document_type: str
    user_id: str
    error_message: str | None = None
    source_ids: list[str]
    updated_at: str


class DeleteDocumentResponse(BaseModel):
    status: str
    document_id: str


class AugmentDocumentRequest(BaseModel):
    sources: list[str] = Field(..., min_length=1)
    additional_notes: str | None = None


class ExportDocumentResponse(BaseModel):
    status: str
    document_id: str
    export: str
    url: str | None = None
    file_base64: str | None = None
    file_name: str | None = None
    content_type: str | None = None


class DocumentReferenceResponse(BaseModel):
    id: str
    title: str
    updated_at: str
