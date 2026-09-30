from abc import ABC, abstractmethod

from domain.value_objects.apa_structure import APASection
from domain.value_objects.document_blueprint import DocumentBlueprint


class DocumentParserPort(ABC):
    """Driven port that converts an uploaded office document to the AST."""

    @abstractmethod
    async def parse(
        self,
        content: bytes,
        blueprint: DocumentBlueprint | None = None,
    ) -> list[APASection]:
        raise NotImplementedError
