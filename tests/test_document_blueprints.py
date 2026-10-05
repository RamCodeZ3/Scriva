from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from api.schemas.documents import CreateDocumentRequest
from domain.entities.document import Document, DocumentStatus
from domain.entities.source import Source, SourceType
from domain.exceptions import DocumentBuildError
from domain.services.table_of_contents_builder import build_index_section
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_blueprint import BLUEPRINTS, get_blueprint
from domain.value_objects.document_node import (
    HEADING_1,
    HEADING_2,
    PARAGRAPH,
    DocumentNode,
    page_break_node,
    text_node,
)
from domain.value_objects.document_type import DocumentType
from infrastructure.ai.document_prompt_guidance import SECTION_GUIDANCE
from infrastructure.ai.gemini_document_writer_adapter import (
    GeminiDocumentWriterAdapter,
)
from infrastructure.export.docx_document_exporter_adapter import (
    DocxDocumentExporterAdapter,
)
from infrastructure.export.odt_document_exporter_adapter import (
    OdtDocumentExporterAdapter,
)
from infrastructure.export.pdf_document_exporter_adapter import (
    PdfDocumentExporterAdapter,
)
from infrastructure.parsers.docx_document_parser_adapter import (
    DocxDocumentParserAdapter,
)


class DocumentBlueprintTest(unittest.TestCase):
    def test_registry_is_complete_and_well_formed(self) -> None:
        self.assertEqual(set(BLUEPRINTS), set(DocumentType))
        for blueprint in BLUEPRINTS.values():
            types = [spec.section_type for spec in blueprint.sections]
            self.assertEqual(len(types), len(set(types)))
            self.assertEqual(types[-1], APASectionType.SOURCES)
            self.assertTrue(blueprint.required_types)

    def test_api_schema_accepts_research_and_rejects_unknown_type(
        self,
    ) -> None:
        request = CreateDocumentRequest(
            user="Student",
            document_type="research",
            sources=["Source"],
        )
        self.assertEqual(request.document_type, DocumentType.RESEARCH)
        with self.assertRaises(ValueError):
            CreateDocumentRequest(
                user="Student",
                document_type="unknown",
                sources=["Source"],
            )

    def test_report_requires_index(self) -> None:
        document = _document(DocumentType.REPORT)
        sections = [
            section
            for section in document.sections
            if section.section_type is not APASectionType.INDEX
        ]
        document.status = DocumentStatus.DRAFTING
        with self.assertRaisesRegex(
            DocumentBuildError,
            "Missing required APA sections: index",
        ):
            document.complete("Report", sections, [])

    def test_research_accepts_optional_sections_and_requires_abstract(
        self,
    ) -> None:
        document = _document(DocumentType.RESEARCH, include_optional=False)
        document.status = DocumentStatus.DRAFTING
        document.complete("Research", document.sections, [])
        self.assertEqual(document.status, DocumentStatus.DONE)

        without_abstract = [
            section
            for section in document.sections
            if section.section_type is not APASectionType.ABSTRACT
        ]
        document.status = DocumentStatus.DRAFTING
        with self.assertRaisesRegex(
            DocumentBuildError,
            "Missing required APA sections: abstract",
        ):
            document.complete("Research", without_abstract, [])

    def test_summary_rejects_index_and_duplicates(self) -> None:
        blueprint = get_blueprint(DocumentType.SUMMARY)
        sections = [
            _section(APASectionType.BODY),
            _section(APASectionType.SOURCES),
        ]
        blueprint.validate_complete(sections)
        with self.assertRaisesRegex(DocumentBuildError, "not allowed"):
            blueprint.validate_complete(sections + [build_index_section()])
        with self.assertRaisesRegex(DocumentBuildError, "Duplicated section"):
            blueprint.validate_complete(sections + [sections[0]])

    def test_sorting_and_style_overrides_follow_blueprint(self) -> None:
        summary = _created_document(DocumentType.SUMMARY)
        report = _created_document(DocumentType.REPORT)
        self.assertEqual(summary.global_style["lineHeight"], 1.5)
        self.assertEqual(report.global_style["lineHeight"], 2.0)

        blueprint = get_blueprint(DocumentType.SUMMARY)
        sorted_sections = blueprint.sort_sections(
            [_section(APASectionType.SOURCES), _section(APASectionType.BODY)]
        )
        self.assertEqual(
            [section.section_type for section in sorted_sections],
            [APASectionType.BODY, APASectionType.SOURCES],
        )

    def test_tree_metadata_and_no_index_for_summary(self) -> None:
        document = _document(DocumentType.SUMMARY)
        tree = document.to_node_tree()
        self.assertEqual(tree["meta"]["style_guide"], "APA7")
        self.assertEqual(tree["meta"]["document_type"], "summary")
        self.assertIsNone(document.get_section(APASectionType.INDEX))

    def test_every_blueprint_section_has_prompt_guidance(self) -> None:
        for document_type, blueprint in BLUEPRINTS.items():
            for spec in blueprint.sections:
                self.assertIn(
                    (document_type, spec.section_type), SECTION_GUIDANCE
                )

    def test_ai_validation_uses_blueprint_before_building_sections(
        self,
    ) -> None:
        adapter = GeminiDocumentWriterAdapter("test-key")
        valid = _ai_response([APASectionType.BODY, APASectionType.SOURCES])
        _, sections, _, _ = adapter._parse_response(
            valid, document_type=DocumentType.SUMMARY
        )
        self.assertEqual(len(sections), 2)

        with self.assertRaisesRegex(
            DocumentBuildError,
            "Missing required APA sections: body",
        ):
            adapter._parse_response(
                _ai_response([APASectionType.SOURCES]),
                document_type=DocumentType.SUMMARY,
            )
        with self.assertRaisesRegex(DocumentBuildError, "not allowed"):
            adapter._parse_response(
                _ai_response(
                    [
                        APASectionType.INDEX,
                        APASectionType.BODY,
                        APASectionType.SOURCES,
                    ]
                ),
                document_type=DocumentType.SUMMARY,
            )

    def test_exporters_render_every_document_type(self) -> None:
        for document_type in DocumentType:
            document = _document(document_type)
            with self.subTest(document_type=document_type.value):
                self.assertTrue(
                    DocxDocumentExporterAdapter()._build_sync(document)
                )
                self.assertTrue(
                    PdfDocumentExporterAdapter()._build_sync(document)[0]
                )
                self.assertTrue(
                    OdtDocumentExporterAdapter()._build_sync(document)
                )

    def test_docx_round_trip_uses_target_blueprint(self) -> None:
        parser = DocxDocumentParserAdapter()
        exporter = DocxDocumentExporterAdapter()
        for document_type in (
            DocumentType.REPORT,
            DocumentType.RESEARCH,
            DocumentType.SUMMARY,
        ):
            document = _document(document_type)
            content = exporter._build_sync(document)
            sections = parser._parse_sync(content, document.blueprint)
            with self.subTest(document_type=document_type.value):
                document.blueprint.validate_complete(sections)


def _created_document(document_type: DocumentType) -> Document:
    user_id = uuid4()
    source = Source.create("Source text", SourceType.TEXT, user_id)
    sources = [source]
    if document_type is DocumentType.SYNTHESIS:
        sources.append(
            Source.create("Second source", SourceType.TEXT, user_id)
        )
    return Document.create(user_id, "Title", document_type, sources)


def _document(
    document_type: DocumentType, *, include_optional: bool = True
) -> Document:
    blueprint = get_blueprint(document_type)
    sections = []
    for spec in blueprint.sections:
        if not spec.required and not include_optional:
            continue
        if spec.section_type is APASectionType.INDEX:
            sections.append(build_index_section())
        else:
            sections.append(_section(spec.section_type))
    now = datetime.now(UTC)
    return Document(
        id=uuid4(),
        user_id=uuid4(),
        title=f"{document_type.value.title()} document",
        document_type=document_type,
        raw_sources=[],
        status=DocumentStatus.DONE,
        sections=sections,
        sources=[],
        created_at=now,
        updated_at=now,
        global_style={
            "lineHeight": blueprint.style_overrides.get("lineHeight", 2.0)
        },
    )


def _section(section_type: APASectionType) -> APASection:
    heading = DocumentNode(
        type=HEADING_1,
        children=(text_node(section_type.value.replace("_", " ").title()),),
    )
    if section_type is APASectionType.PRESENTATION:
        body = (
            DocumentNode(type=PARAGRAPH, children=(text_node("Student"),)),
            page_break_node(),
        )
    elif section_type is APASectionType.BODY:
        body = (
            DocumentNode(type=HEADING_2, children=(text_node("Theme"),)),
            DocumentNode(type=PARAGRAPH, children=(text_node("Content"),)),
        )
    else:
        body = (
            DocumentNode(type=PARAGRAPH, children=(text_node("Content"),)),
        )
    return APASection(section_type, heading, body)


def _ai_response(section_types: list[APASectionType]) -> str:
    import json

    return json.dumps(
        {
            "title": "Document title",
            "global_style": {},
            "sections": [
                {
                    "section_type": section_type.value,
                    "title": section_type.value.replace("_", " ").title(),
                    "nodes": [
                        {
                            "type": "paragraph",
                            "styles": {"textAlign": "justify"},
                            "children": [{"text": "Content"}],
                        }
                    ],
                }
                for section_type in section_types
            ],
            "references": [],
        }
    )
