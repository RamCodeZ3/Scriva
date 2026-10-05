import unittest
from datetime import UTC, datetime
from uuid import uuid4

from application.exceptions import NoSourcesExtractedError
from application.ports.source_extractor_port import ExtractedSource
from application.use_cases.process_document_use_case import (
    ProcessDocumentUseCase,
)
from domain.entities.document import Document
from domain.entities.source import Source, SourceStatus, SourceType
from domain.exceptions import DocumentBuildError
from domain.services.citation_service import resolve_citations
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    HEADING_1,
    PARAGRAPH,
    DocumentNode,
    text_node,
)
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from infrastructure.persistence.supabase_source_repository import (
    SupabaseSourceRepository,
)


class CitationIntegrityTests(unittest.TestCase):
    def test_personal_and_group_authors_are_apa_formatted(self) -> None:
        personal = _source(
            author="Javier Reyes Ochoa", title="Python", year=2023
        )
        group = _source(author="Coursera Staff", title="Programming")
        result = resolve_citations(
            [_section(personal, group)], [personal, group], "en"
        )

        self.assertEqual(result.references[0].author, "Coursera Staff")
        self.assertEqual(result.references[1].author, "Reyes Ochoa, J.")
        self.assertIn(
            "(2023, January 2)", result.references[1].to_apa_string()
        )

    def test_same_author_year_is_disambiguated_by_title(self) -> None:
        beta = _source(author="Javier Reyes Ochoa", title="Beta", year=2023)
        alpha = _source(
            author="Javier Reyes Ochoa", title="The Alpha", year=2023
        )
        result = resolve_citations(
            [_section(beta, alpha)], [beta, alpha], "en"
        )

        self.assertEqual(
            [reference.year_suffix for reference in result.references],
            ["a", "b"],
        )
        body = result.sections[0].body_nodes[0].plain_text()
        self.assertIn("(Reyes Ochoa, 2023b)", body)
        self.assertIn("(Reyes Ochoa, 2023a)", body)

    def test_missing_metadata_uses_localized_fallbacks(self) -> None:
        source = _source(source_type=SourceType.TEXT)
        result = resolve_citations([_section(source)], [source], "es")

        reference = result.references[0]
        self.assertEqual(reference.author, "")
        self.assertEqual(reference.title, "Texto proporcionado por el usuario")
        self.assertIn("(s. f.)", reference.to_apa_string())

    def test_secondary_citation_adds_only_consulted_reference(self) -> None:
        source = _source(author="Coursera Staff", title="Python", year=2023)
        section = _section(
            source,
            token=f"[[cite:{source.id}|secondary=RedMonk, 2021]]",
        )
        result = resolve_citations([section], [source], "en")

        self.assertEqual(len(result.references), 1)
        self.assertIn(
            "(RedMonk, 2021, as cited in Coursera Staff, 2023)",
            result.sections[0].body_nodes[0].plain_text(),
        )

    def test_unknown_or_failed_source_key_is_rejected(self) -> None:
        failed = _source()
        failed.status = SourceStatus.FAILED
        with self.assertRaisesRegex(
            DocumentBuildError, "unknown or unavailable"
        ):
            resolve_citations([_section(failed)], [failed], "en")

    def test_uncited_source_is_excluded_and_references_are_sorted(
        self,
    ) -> None:
        zebra = _source(author="Zebra Team", title="Z")
        alpha = _source(author="Alpha Team", title="A")
        unused = _source(author="Unused Team", title="U")
        result = resolve_citations(
            [_section(zebra, alpha)], [zebra, alpha, unused], "en"
        )

        self.assertEqual(
            [reference.author for reference in result.references],
            ["Alpha Team", "Zebra Team"],
        )

    def test_resolved_citation_keeps_source_identity_for_augmentation(
        self,
    ) -> None:
        source = _source(author="Coursera Staff", title="Python", year=2023)
        initial = resolve_citations([_section(source)], [source], "en")

        repeated = resolve_citations(initial.sections, [source], "en")

        self.assertEqual(len(repeated.references), 1)
        self.assertEqual(repeated.references[0].title, "Python")
        citation_node = repeated.sections[0].body_nodes[0]
        self.assertEqual(
            citation_node.metadata["citationSourceIds"], [str(source.id)]
        )

    def test_augmentation_drops_an_existing_reference_no_longer_cited(
        self,
    ) -> None:
        kept = _source(author="Alpha Team", title="Kept", year=2023)
        stale = _source(author="Beta Team", title="Stale", year=2022)
        stale_reference = resolve_citations(
            [_section(stale)], [stale], "en"
        ).references[0]

        result = resolve_citations(
            [_section(kept)],
            [kept, stale],
            "en",
            existing_references=[stale_reference],
        )

        self.assertEqual([item.title for item in result.references], ["Kept"])

    def test_legacy_personal_reference_is_kept_when_still_cited(self) -> None:
        source = _source(
            author="Javier Reyes Ochoa", title="Python", year=2023
        )
        reference = resolve_citations(
            [_section(source)], [source], "en"
        ).references[0]
        legacy_section = _section(
            token="A supported claim (Reyes Ochoa, 2023)."
        )

        result = resolve_citations(
            [legacy_section],
            [source],
            "en",
            existing_references=[reference],
        )

        self.assertEqual(result.references, [reference])

    def test_long_url_survives_source_persistence_mapping(self) -> None:
        url = (
            "https://www.coursera.org/articles/"
            "what-is-python-used-for-a-beginners-guide-to-using-python"
        )
        source = _source(source_type=SourceType.WEB, raw=url)
        source.canonical_url = url
        row = SupabaseSourceRepository._to_row(source)
        loaded = SupabaseSourceRepository._to_entity(
            {**row, "created_at": datetime.now(UTC).isoformat()}
        )

        self.assertEqual(loaded.raw, url)
        self.assertEqual(loaded.canonical_url, url)
        result = resolve_citations([_section(loaded)], [loaded], "en")
        self.assertEqual(result.references[0].url, url)

    def test_synthesis_requires_two_sources(self) -> None:
        source = _source()
        with self.assertRaisesRegex(DocumentBuildError, "at least 2 sources"):
            Document.create(
                uuid4(), "Synthesis", DocumentType.SYNTHESIS, [source]
            )


class SynthesisExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_extraction_marks_synthesis_failed(self) -> None:
        user_id = uuid4()
        first = Source.create("first", SourceType.TEXT, user_id)
        second = Source.create("second", SourceType.TEXT, user_id)
        document = Document.create(
            user_id,
            "Synthesis",
            DocumentType.SYNTHESIS,
            [first, second],
        )
        documents = _DocumentRepository(document)
        sources = _SourceRepository([first, second])
        use_case = ProcessDocumentUseCase(
            documents,
            sources,
            _ExtractorFactory(),
            _UnexpectedWriter(),
        )

        with self.assertRaisesRegex(
            NoSourcesExtractedError, "successfully extracted sources"
        ):
            await use_case.execute(
                document.id, PresentationInfo(student_name="Student")
            )

        self.assertEqual(document.status.value, "failed")
        self.assertEqual(document.error_stage, "source_extraction")
        self.assertEqual(first.status, SourceStatus.EXTRACTED)
        self.assertEqual(second.status, SourceStatus.FAILED)


def _source(
    *,
    author: str | None = None,
    title: str | None = None,
    year: int | None = None,
    source_type: SourceType = SourceType.WEB,
    raw: str | None = None,
) -> Source:
    raw = raw or f"https://example.com/{uuid4()}"
    source = Source.create(raw, source_type, uuid4())
    source.mark_extracted(
        "Extracted content",
        author=author,
        title=title,
        published_at=datetime(year, 1, 2, tzinfo=UTC) if year else None,
        canonical_url=raw if source_type is SourceType.WEB else None,
    )
    return source


def _section(
    *sources: Source,
    token: str | None = None,
) -> APASection:
    citations = token or " ".join(
        f"Claim [[cite:{source.id}]]" for source in sources
    )
    return APASection(
        APASectionType.BODY,
        DocumentNode(type=HEADING_1, children=(text_node("Body"),)),
        (DocumentNode(type=PARAGRAPH, children=(text_node(citations),)),),
    )


class _DocumentRepository:
    def __init__(self, document: Document) -> None:
        self.document = document

    async def get_by_id(self, document_id):
        return self.document if document_id == self.document.id else None

    async def save(self, document: Document) -> None:
        self.document = document


class _SourceRepository:
    def __init__(self, sources: list[Source]) -> None:
        self.sources = {source.id: source for source in sources}

    async def get_by_id(self, source_id):
        return self.sources.get(source_id)

    async def save(self, source: Source) -> None:
        self.sources[source.id] = source


class _ExtractorFactory:
    def get_extractor(self, source_type):
        return _PartialExtractor()


class _PartialExtractor:
    async def extract_with_metadata(self, raw: str) -> ExtractedSource:
        if raw == "second":
            raise RuntimeError("Unavailable")
        return ExtractedSource(content="Extracted content")


class _UnexpectedWriter:
    async def write(self, **kwargs):
        raise AssertionError("Writer must not run with too few sources")


if __name__ == "__main__":
    unittest.main()
