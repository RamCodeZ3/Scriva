from __future__ import annotations

import os
from functools import lru_cache
from uuid import UUID

from application.ports.document_exporter_resolver_port import (
    DocumentExporterResolverPort,
)
from application.ports.document_parser_port import DocumentParserPort
from application.ports.document_repository_port import DocumentRepositoryPort
from application.ports.document_writer_port import DocumentWriterPort
from application.ports.docx_cache_port import DocxCachePort
from application.ports.extractor_factory_port import ExtractorFactoryPort
from application.ports.google_credentials_port import GoogleCredentialsPort
from application.ports.source_repository_port import SourceRepositoryPort
from application.ports.user_repository_port import UserRepositoryPort
from application.use_cases.augment_document_use_case import (
    AugmentDocumentUseCase,
)
from application.use_cases.connect_google_credentials_use_case import (
    ConnectGoogleCredentialsUseCase,
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
from application.use_cases.get_user_source_use_case import GetUserSourceUseCase
from application.use_cases.list_user_documents_use_case import (
    ListUserDocumentsUseCase,
)
from application.use_cases.list_user_sources_use_case import (
    ListUserSourcesUseCase,
)
from application.use_cases.process_document_use_case import (
    ProcessDocumentUseCase,
)
from application.use_cases.update_document_use_case import (
    UpdateDocumentUseCase,
)
from domain.entities.source import SourceType
from domain.entities.user import User
from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException, status
from infrastructure.ai.gemini_document_writer_adapter import (
    GeminiDocumentWriterAdapter,
)
from infrastructure.auth.google_oauth_token_provider import (
    GoogleOAuthTokenProvider,
)
from infrastructure.auth.supabase_jwt_auth import (
    InvalidTokenError,
    SupabaseJWTAuth,
)
from infrastructure.cache.local_docx_cache import LocalDocxCacheService
from infrastructure.export.document_exporter_resolver_adapter import (
    DocumentExporterResolverAdapter,
)
from infrastructure.export.docx_document_exporter_adapter import (
    DocxDocumentExporterAdapter,
)
from infrastructure.export.pdf_document_exporter_adapter import (
    PdfDocumentExporterAdapter,
)
from infrastructure.extractors.extractor_factory_adapter import (
    ExtractorFactoryAdapter,
)
from infrastructure.extractors.file_extractor_adapter import (
    FileExtractorAdapter,
)
from infrastructure.extractors.text_extractor_adapter import (
    PlainTextExtractorAdapter,
)
from infrastructure.extractors.web_extractor_adapter import WebExtractorAdapter
from infrastructure.extractors.whisper_media_extractor_adapter import (
    WhisperMediaExtractorAdapter,
)
from infrastructure.extractors.youtube_extractor_adapter import (
    YoutubeExtractorAdapter,
)
from infrastructure.jobs.sync_job_dispatcher_adapter import (
    SyncJobDispatcherAdapter,
)
from infrastructure.parsers.docx_document_parser_adapter import (
    DocxDocumentParserAdapter,
)
from infrastructure.persistence.supabase_client import build_supabase_client
from infrastructure.persistence.supabase_document_repository import (
    SupabaseDocumentRepository,
)
from infrastructure.persistence.supabase_google_credentials_repository import (
    SupabaseGoogleCredentialsRepository,
)
from infrastructure.persistence.supabase_source_repository import (
    SupabaseSourceRepository,
)
from infrastructure.persistence.supabase_user_repository import (
    SupabaseUserRepository,
)

# ── Process-wide singletons ─────────────────────────────────────────────


@lru_cache
def get_supabase_client():
    return build_supabase_client(
        url=os.environ["SUPABASE_URL"],
        key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


@lru_cache
def get_jwt_auth() -> SupabaseJWTAuth:
    return SupabaseJWTAuth(
        project_url=os.environ["SUPABASE_URL"],
        api_key=os.environ["SUPABASE_ANON_KEY"],
        legacy_secret=os.environ.get("SUPABASE_JWT_SECRET"),
    )


@lru_cache
def get_extractor_factory() -> ExtractorFactoryPort:
    media_extractor = WhisperMediaExtractorAdapter(
        model_name=os.environ.get("WHISPER_MODEL", "base"),
        device=os.environ.get("WHISPER_DEVICE"),
    )
    return ExtractorFactoryAdapter(
        {
            SourceType.WEB: WebExtractorAdapter(),
            SourceType.YOUTUBE: YoutubeExtractorAdapter(),
            SourceType.FILE: FileExtractorAdapter(
                media_extractor=media_extractor
            ),
            SourceType.TEXT: PlainTextExtractorAdapter(),
        }
    )


@lru_cache
def get_document_writer() -> DocumentWriterPort:
    return GeminiDocumentWriterAdapter(api_key=os.environ["GEMINI_API_KEY"])


@lru_cache
def get_google_credentials_repository() -> GoogleCredentialsPort:
    load_dotenv()
    return SupabaseGoogleCredentialsRepository(
        get_supabase_client(),
        encryption_key=os.environ["GOOGLE_TOKEN_ENCRYPTION_KEY"],
    )


@lru_cache
def get_google_oauth_token_provider() -> GoogleOAuthTokenProvider:
    load_dotenv()
    return GoogleOAuthTokenProvider(
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
    )


@lru_cache
def get_pdf_document_exporter() -> PdfDocumentExporterAdapter:
    return PdfDocumentExporterAdapter()


@lru_cache
def get_docx_document_exporter() -> DocxDocumentExporterAdapter:
    return DocxDocumentExporterAdapter()


@lru_cache
def get_document_parser() -> DocumentParserPort:
    return DocxDocumentParserAdapter()


@lru_cache
def get_docx_cache() -> DocxCachePort:
    cache_size_mb = int(os.environ.get("DOCX_CACHE_SIZE_MB", "1024"))
    return LocalDocxCacheService(
        directory=os.environ.get("DOCX_CACHE_DIR", "./storage/cache/docx"),
        size_limit=cache_size_mb * 1024**2,
    )


@lru_cache
def get_document_exporter_resolver() -> DocumentExporterResolverPort:
    return DocumentExporterResolverAdapter(
        pdf_exporter=get_pdf_document_exporter(),
        google_credentials_repository=get_google_credentials_repository(),
        google_token_provider=get_google_oauth_token_provider(),
    )


# ── Repositories ─────────────────────────────────────────────────────────


def get_user_repository() -> UserRepositoryPort:
    return SupabaseUserRepository(get_supabase_client())


def get_source_repository() -> SourceRepositoryPort:
    return SupabaseSourceRepository(get_supabase_client())


def get_document_repository(
    source_repository: SourceRepositoryPort = Depends(get_source_repository),
) -> DocumentRepositoryPort:
    return SupabaseDocumentRepository(get_supabase_client(), source_repository)


# ── Auth ─────────────────────────────────────────────────────────────────


async def get_current_user_id(
    authorization: str | None = Header(default=None, alias="Authorization"),
    jwt_auth: SupabaseJWTAuth = Depends(get_jwt_auth),
) -> UUID:
    authorization = authorization or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing or malformed Authorization header. Expected: "
                "'Bearer <token>'."
            ),
        )

    try:
        payload = jwt_auth.decode(token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has no 'sub' claim.",
        )

    try:
        return UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 'sub' is not a valid UUID.",
        ) from exc


async def get_current_user(
    user_id: UUID = Depends(get_current_user_id),
    user_repository: UserRepositoryPort = Depends(get_user_repository),
) -> User:
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This account is not registered in the documents service yet."
            ),
        )
    return user


# ── Use cases ────────────────────────────────────────────────────────────


def get_process_document_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    source_repository: SourceRepositoryPort = Depends(get_source_repository),
    extractor_factory: ExtractorFactoryPort = Depends(get_extractor_factory),
    document_writer: DocumentWriterPort = Depends(get_document_writer),
) -> ProcessDocumentUseCase:
    return ProcessDocumentUseCase(
        document_repository=document_repository,
        source_repository=source_repository,
        extractor_factory=extractor_factory,
        document_writer=document_writer,
    )


def get_create_document_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    source_repository: SourceRepositoryPort = Depends(get_source_repository),
    user_repository: UserRepositoryPort = Depends(get_user_repository),
    process_use_case: ProcessDocumentUseCase = Depends(
        get_process_document_use_case
    ),
    exporter=Depends(get_docx_document_exporter),
    cache: DocxCachePort = Depends(get_docx_cache),
) -> CreateDocumentUseCase:
    dispatcher = SyncJobDispatcherAdapter(process_use_case)
    return CreateDocumentUseCase(
        document_repository=document_repository,
        source_repository=source_repository,
        user_repository=user_repository,
        job_dispatcher=dispatcher,
        exporter=exporter,
        cache=cache,
    )


def get_get_document_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    exporter=Depends(get_docx_document_exporter),
    cache: DocxCachePort = Depends(get_docx_cache),
) -> GetDocumentUseCase:
    return GetDocumentUseCase(document_repository, exporter, cache)


def get_update_document_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    parser: DocumentParserPort = Depends(get_document_parser),
    exporter=Depends(get_docx_document_exporter),
    cache: DocxCachePort = Depends(get_docx_cache),
) -> UpdateDocumentUseCase:
    return UpdateDocumentUseCase(document_repository, parser, exporter, cache)


def get_delete_document_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    cache: DocxCachePort = Depends(get_docx_cache),
) -> DeleteDocumentUseCase:
    return DeleteDocumentUseCase(document_repository, cache)


def get_augment_document_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    source_repository: SourceRepositoryPort = Depends(get_source_repository),
    extractor_factory: ExtractorFactoryPort = Depends(get_extractor_factory),
    document_writer: DocumentWriterPort = Depends(get_document_writer),
    exporter=Depends(get_docx_document_exporter),
    cache: DocxCachePort = Depends(get_docx_cache),
) -> AugmentDocumentUseCase:
    return AugmentDocumentUseCase(
        document_repository=document_repository,
        source_repository=source_repository,
        extractor_factory=extractor_factory,
        document_writer=document_writer,
        exporter=exporter,
        cache=cache,
    )


def get_export_document_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    exporter_resolver: DocumentExporterResolverPort = Depends(
        get_document_exporter_resolver
    ),
) -> ExportDocumentUseCase:
    return ExportDocumentUseCase(
        document_repository=document_repository,
        exporter_resolver=exporter_resolver,
    )


def get_connect_google_credentials_use_case() -> (
    ConnectGoogleCredentialsUseCase
):
    return ConnectGoogleCredentialsUseCase(
        credentials=get_google_credentials_repository(),
        oauth_tokens=get_google_oauth_token_provider(),
    )


def get_list_user_documents_use_case(
    document_repository: DocumentRepositoryPort = Depends(
        get_document_repository
    ),
    user_repository: UserRepositoryPort = Depends(get_user_repository),
) -> ListUserDocumentsUseCase:
    return ListUserDocumentsUseCase(
        document_repository=document_repository,
        user_repository=user_repository,
    )


def get_list_user_sources_use_case(
    source_repository: SourceRepositoryPort = Depends(get_source_repository),
) -> ListUserSourcesUseCase:
    return ListUserSourcesUseCase(source_repository)


def get_get_user_source_use_case(
    source_repository: SourceRepositoryPort = Depends(get_source_repository),
) -> GetUserSourceUseCase:
    return GetUserSourceUseCase(source_repository)
