from uuid import UUID

from application.use_cases.get_user_source_use_case import GetUserSourceUseCase
from application.use_cases.list_user_sources_use_case import (
    ListUserSourcesUseCase,
)
from domain.entities.user import User
from fastapi import APIRouter, Depends

from api.deps import (
    get_current_user,
    get_get_user_source_use_case,
    get_list_user_sources_use_case,
)
from api.schemas.sources import (
    SourceDetailResponseSchema,
    SourceResponseSchema,
)

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("/{user_id}", response_model=list[SourceResponseSchema])
async def list_user_sources(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    use_case: ListUserSourcesUseCase = Depends(get_list_user_sources_use_case),
) -> list[SourceResponseSchema]:
    sources = await use_case.execute(user_id, current_user.id)
    return [
        SourceResponseSchema(
            id=source.id,
            type=source.source_type.value,
            raw=source.raw,
            char_count=source.char_count,
            created_at=source.created_at,
            bibliographic=source.bibliographic,
        )
        for source in sources
    ]


@router.get(
    "/{user_id}/{source_id}", response_model=SourceDetailResponseSchema
)
async def get_user_source(
    user_id: UUID,
    source_id: UUID,
    current_user: User = Depends(get_current_user),
    use_case: GetUserSourceUseCase = Depends(get_get_user_source_use_case),
) -> SourceDetailResponseSchema:
    source = await use_case.execute(user_id, source_id, current_user.id)
    return SourceDetailResponseSchema(
        id=source.id,
        type=source.source_type.value,
        content=source.content,
        raw=source.raw,
        char_count=source.char_count,
        created_at=source.created_at,
        bibliographic=source.bibliographic,
    )
