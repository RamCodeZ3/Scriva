from __future__ import annotations

from uuid import UUID

from application.dtos.document_dtos import DocumentProgressCallback
from application.ports.document_job_dispatcher_port import (
    DocumentJobDispatcherPort,
)
from application.use_cases.process_document_use_case import (
    ProcessDocumentUseCase,
)
from fastapi import BackgroundTasks


class FastAPIBackgroundJobDispatcher(DocumentJobDispatcherPort):
    def __init__(
        self,
        background_tasks: BackgroundTasks,
        process_use_case: ProcessDocumentUseCase,
    ) -> None:
        self._background_tasks = background_tasks
        self._process_use_case = process_use_case

    async def dispatch(
        self,
        document_id: UUID,
        on_progress: DocumentProgressCallback | None = None,
    ) -> None:
        self._background_tasks.add_task(self._run, document_id, on_progress)

    async def _run(
        self,
        document_id: UUID,
        on_progress: DocumentProgressCallback | None,
    ) -> None:
        await self._process_use_case.execute(document_id, on_progress)
