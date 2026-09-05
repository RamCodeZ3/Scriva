from abc import ABC, abstractmethod
from uuid import UUID

from application.dtos.document_dtos import DocumentProgressCallback


class DocumentJobDispatcherPort(ABC):
    """
    Driven port used to enqueue the extraction + AI + export pipeline
    so the HTTP endpoint can return immediately (202 Accepted) while the
    client polls the status endpoint. Adapter can be as simple as
    FastAPI's BackgroundTasks, or a real queue (Celery, SQS, etc).
    """

    @abstractmethod
    async def dispatch(
        self,
        document_id: UUID,
        on_progress: DocumentProgressCallback | None = None,
    ) -> None:
        raise NotImplementedError
