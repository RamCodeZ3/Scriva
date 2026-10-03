import unittest
from datetime import UTC, datetime
from uuid import uuid4

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
from infrastructure.persistence.supabase_source_repository import (
    SupabaseSourceRepository,
)


class CitationIntegrityTests(unittest.TestCase):
    def test_personal_and_group_authors_are_apa_formatted(self) -> None:
        personal = _source(author="Javier Reyes Ochoa", title="Python")
        group = _source(author="Coursera Staff", title="Programming")
        result = resolve_citations(
            [_section(personal, group)], [personal, group], "en"
        )

        self.assertEqual(result.references[0].author, "Coursera Staff")
        self.assertEqual(result.references[1].author, "Reyes Ochoa, J.")

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


if __name__ == "__main__":
    unittest.main()
