from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from application.ports.document_exporter_port import DocumentExporterPort


class UnsupportedExportTargetError(Exception):
    pass


class DocumentExporterResolverPort(ABC):
    @abstractmethod
    async def resolve(
        self, export_target: str, user_id: UUID
    ) -> DocumentExporterPort:
        """
        Raises `UnsupportedExportTargetError` if `export_target` is
        unknown, or if it's 'google_docs' and the user has no linked
        account / the refresh token can't be exchanged.
        """
        raise NotImplementedError
