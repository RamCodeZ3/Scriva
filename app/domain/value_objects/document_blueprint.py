from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_type import DocumentType


@dataclass(frozen=True)
class SectionSpec:
    section_type: APASectionType
    required: bool = True


@dataclass(frozen=True)
class DocumentBlueprint:
    document_type: DocumentType
    sections: tuple[SectionSpec, ...]
    style_guide: str = "APA7"
    style_overrides: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        types = [spec.section_type for spec in self.sections]
        if not types:
            raise ValueError("A blueprint needs at least one section.")
        if len(types) != len(set(types)):
            raise ValueError("Blueprint sections must be unique.")

    @property
    def required_types(self) -> frozenset[APASectionType]:
        return frozenset(
            spec.section_type for spec in self.sections if spec.required
        )

    @property
    def allowed_types(self) -> frozenset[APASectionType]:
        return frozenset(spec.section_type for spec in self.sections)

    def has(self, section_type: APASectionType) -> bool:
        return section_type in self.allowed_types

    def order_of(self, section_type: APASectionType) -> int:
        for index, spec in enumerate(self.sections):
            if spec.section_type == section_type:
                return index
        raise DocumentBuildError(
            f"Section '{section_type.value}' is not allowed in a "
            f"'{self.document_type.value}' document."
        )

    def validate_membership(self, sections: Sequence[APASection]) -> None:
        """Reject unexpected or duplicated sections (not missing ones)."""
        seen: set[APASectionType] = set()
        for section in sections:
            self.order_of(section.section_type)
            if section.section_type in seen:
                raise DocumentBuildError(
                    f"Duplicated section: '{section.section_type.value}'."
                )
            seen.add(section.section_type)

    def validate_complete(self, sections: Sequence[APASection]) -> None:
        if not sections:
            raise DocumentBuildError(
                "A document must have at least one section."
            )
        self.validate_membership(sections)
        missing = self.required_types - {
            section.section_type for section in sections
        }
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise DocumentBuildError(f"Missing required APA sections: {names}")

    def sort_sections(
        self, sections: Sequence[APASection]
    ) -> list[APASection]:
        self.validate_membership(sections)
        return sorted(
            sections, key=lambda section: self.order_of(section.section_type)
        )


BLUEPRINTS: dict[DocumentType, DocumentBlueprint] = {
    DocumentType.REPORT: DocumentBlueprint(
        document_type=DocumentType.REPORT,
        sections=tuple(
            SectionSpec(section_type)
            for section_type in (
                APASectionType.PRESENTATION,
                APASectionType.INDEX,
                APASectionType.INTRODUCTION,
                APASectionType.BODY,
                APASectionType.CONCLUSION,
                APASectionType.SOURCES,
            )
        ),
    )
}


def get_blueprint(document_type: DocumentType) -> DocumentBlueprint:
    try:
        return BLUEPRINTS[document_type]
    except KeyError as exc:
        raise DocumentBuildError(
            f"No blueprint defined for '{document_type.value}'."
        ) from exc
