from datetime import datetime
from uuid import UUID

from domain.value_objects.bib_metadata import BibMetadata
from pydantic import BaseModel


class SourceResponseSchema(BaseModel):
    id: UUID
    type: str
    raw: str
    char_count: int
    created_at: datetime
    bibliographic: BibMetadata | None = None


class SourceDetailResponseSchema(SourceResponseSchema):
    content: str
