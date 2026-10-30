"""Enrichment tests use mocked providers and local fixtures."""

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from application.ports.bib_metadata_port import BibMetadata
from docx import Document
from domain.entities.source import Source
from domain.services.citation_service import resolve_citations
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    HEADING_1,
    PARAGRAPH,
    DocumentNode,
    text_node,
)
from infrastructure.extractors.youtube_extractor_adapter import (
    YoutubeExtractorAdapter,
)
from infrastructure.metadata.common import set_date, youtube_id
from infrastructure.metadata.enricher import (
    MetadataEnricherAdapter,
    detect_type,
)
from infrastructure.metadata.http import MetadataHTTPClient
from infrastructure.metadata.web import read_web
from infrastructure.persistence.supabase_source_repository import (
    SupabaseSourceRepository,
)
from pptx import Presentation

URL = "https://www.youtube.com/watch?v=abcdefghijk"
INFO = {
    "title": "  Actual   title - YouTube",
    "channel": "Science Channel",
    "upload_date": "20240102",
    "duration": 120.5,
    "webpage_url": URL,
}
CROSSREF = {
    "message": {
        "title": ["Verified paper"],
        "author": [
            {"family": "Reyes", "given": "Ana María"},
            {"family": "Smith", "given": "John"},
        ],
        "issued": {"date-parts": [[2023]]},
        "container-title": ["Journal"],
        "publisher": "Publisher",
        "URL": "https://doi.org/10.1234/test",
    }
}


class MetadataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.http = MagicMock(spec=MetadataHTTPClient)
        self.http.get_json = AsyncMock()
        self.enricher = MetadataEnricherAdapter(http=self.http)

    @patch("infrastructure.metadata.youtube.yt_dlp.YoutubeDL")
    async def test_youtube_real_metadata_and_no_download(self, factory):
        ydl = factory.return_value.__enter__.return_value
        ydl.extract_info.return_value = INFO
        meta = await self.enricher.enrich(URL)
        self.assertEqual(meta.title, "Actual title")
        self.assertEqual(meta.author, "Science Channel")
        self.assertEqual(meta.published_at, date(2024, 1, 2))
        self.assertEqual(meta.url, URL)
        self.assertEqual(meta.duration_seconds, 120)
        self.assertEqual(meta.origins["author"], "yt_dlp")
        self.assertFalse(meta.needs_review)
        ydl.extract_info.assert_called_once_with(URL, download=False)
        self.assertTrue(factory.call_args.args[0]["skip_download"])
        self.assertEqual(factory.call_args.args[0]["socket_timeout"], 10)
        self.http.get_json.assert_not_awaited()

    @patch(
        "infrastructure.metadata.youtube._extract_info",
        side_effect=RuntimeError("IP blocked"),
    )
    async def test_oembed_fallback(self, _extract):
        self.http.get_json.return_value = {
            "title": "Fallback title",
            "author_name": "Channel Name",
        }
        meta = await self.enricher.enrich(URL)
        self.assertEqual(meta.author, "Channel Name")
        self.assertEqual(meta.origins["title"], "oembed")
        self.assertIsNone(meta.published_at)
        self.assertTrue(meta.needs_review)

    @patch("infrastructure.metadata.youtube._extract_info", return_value={})
    async def test_data_api_fills_missing_date_without_erasing_oembed(
        self, _extract
    ):
        self.enricher = MetadataEnricherAdapter(
            http=self.http, youtube_api_key="test-key"
        )
        self.http.get_json.side_effect = [
            {"title": "oEmbed title", "author_name": "Channel"},
            {
                "items": [
                    {
                        "snippet": {
                            "title": "API title",
                            "channelTitle": "API channel",
                            "publishedAt": "2020-06-07T10:00:00Z",
                        }
                    }
                ]
            },
        ]
        meta = await self.enricher.enrich(URL)
        self.assertEqual(meta.title, "oEmbed title")
        self.assertEqual(meta.published_at, date(2020, 6, 7))
        self.assertEqual(meta.origins["published_at"], "youtube_api")

    @patch("infrastructure.metadata.youtube._extract_info", return_value={})
    async def test_api_disabled_without_key_and_failure_is_tolerated(self, _):
        self.http.get_json.side_effect = httpx.ConnectError("offline")
        meta = await self.enricher.enrich(URL)
        self.assertIsNone(meta.title)
        self.assertEqual(meta.url, URL)
        self.http.get_json.assert_awaited_once()

    @patch("infrastructure.metadata.youtube._extract_info", return_value=INFO)
    async def test_cache_normalizes_urls_and_returns_independent_values(
        self, fn
    ):
        first = await self.enricher.enrich("https://youtu.be/abcdefghijk")
        first.title = "User modification"
        second = await self.enricher.enrich(URL)
        self.assertEqual(second.title, "Actual title")
        self.assertEqual(fn.call_count, 1)

    @patch("infrastructure.metadata.pdf.PdfReader")
    async def test_pdf_doi_crossref_priority_and_year_precision(self, reader):
        reader.return_value.pages = [MagicMock()]
        reader.return_value.pages[
            0
        ].extract_text.return_value = "Article DOI: 10.1234/test."
        reader.return_value.metadata = MagicMock(
            title="Draft",
            author="Local author",
            creation_date=datetime(2021, 2, 3),
        )
        self.http.get_json.return_value = CROSSREF
        meta = await self.enricher.enrich("paper.pdf")
        self.assertEqual(meta.title, "Verified paper")
        self.assertEqual(meta.origins["title"], "crossref")
        self.assertEqual(meta.author, "Reyes, A. M.; Smith, J.")
        self.assertEqual(meta.published_year, 2023)
        self.assertIsNone(meta.published_at)
        self.assertEqual(meta.publisher, "Publisher")
        self.assertFalse(meta.needs_review)
        self.assertIn("10.1234%2Ftest", self.http.get_json.call_args.args[0])

    @patch("infrastructure.metadata.pdf.PdfReader")
    async def test_crossref_failure_keeps_pdf_values(self, reader):
        reader.return_value.pages = [MagicMock()]
        reader.return_value.pages[0].extract_text.return_value = "10.1234/test"
        reader.return_value.metadata = MagicMock(
            title="Local title",
            author="Real Author",
            creation_date=datetime(2019, 1, 1),
        )
        self.http.get_json.side_effect = TimeoutError
        meta = await self.enricher.enrich("paper.pdf")
        self.assertEqual(meta.title, "Local title")
        self.assertEqual(meta.author, "Real Author")
        self.assertTrue(meta.needs_review)

    async def test_docx_generic_author_and_pptx_properties(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "My document.docx"
            doc = Document()
            doc.core_properties.author = "python-docx"
            doc.core_properties.title = "Actual document"
            doc.save(path)
            meta = await self.enricher.enrich(str(path))
            self.assertIsNone(meta.author)
            self.assertEqual(meta.title, "Actual document")
            self.assertTrue(meta.needs_review)
            deck_path = Path(folder) / "deck.pptx"
            deck = Presentation()
            deck.core_properties.title = "Deck title"
            deck.core_properties.author = "Example Organization"
            deck.save(deck_path)
            meta = await self.enricher.enrich(str(deck_path))
            self.assertEqual(meta.author, "Example Organization")
            self.assertEqual(meta.origins["title"], "doc_properties")
            self.assertTrue(meta.needs_review)

    @patch("infrastructure.metadata.media.subprocess.run")
    async def test_video_tags_and_ffprobe_timeout(self, run):
        run.return_value.stdout = json.dumps(
            {
                "format": {
                    "tags": {
                        "TITLE": "Video title",
                        "artist": "Creator",
                        "creation_time": "2022-03-04T12:00:00Z",
                    },
                    "duration": "12.3",
                }
            }
        )
        meta = await self.enricher.enrich("video.mp4")
        self.assertEqual(meta.title, "Video title")
        self.assertEqual(meta.duration_seconds, 12)
        self.assertEqual(meta.published_at, date(2022, 3, 4))
        self.assertTrue(meta.needs_review)
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    @patch("mutagen.File")
    async def test_audio_tags_and_year(self, reader):
        reader.return_value = {
            "title": ["Song"],
            "artist": ["Band Name"],
            "date": ["1999"],
        }
        meta = await self.enricher.enrich("audio.mp3")
        self.assertEqual(meta.author, "Band Name")
        self.assertEqual(meta.published_year, 1999)
        self.assertIsNone(meta.published_at)
        self.assertTrue(meta.needs_review)

    async def test_text_empty_and_unreadable_file_title_fallback(self):
        meta = await self.enricher.enrich("User supplied plain text", "text")
        self.assertIsNone(meta.title)
        self.assertTrue(meta.needs_review)
        meta = await self.enricher.enrich("/missing/Meaningful name.pdf")
        self.assertEqual(meta.title, "Meaningful name")
        self.assertEqual(meta.origins["title"], "ninguno")

    @patch("infrastructure.metadata.youtube._extract_info", return_value=INFO)
    @patch(
        "infrastructure.extractors.youtube_extractor_adapter."
        "YouTubeTranscriptApi"
    )
    async def test_transcription_remains_independent_and_reference_is_real(
        self, transcript, _info
    ):
        transcript.return_value.fetch.return_value = [
            MagicMock(text="Actual transcript")
        ]
        result = await YoutubeExtractorAdapter(
            metadata_enricher=self.enricher
        ).extract_with_metadata(URL)
        transcript.return_value.fetch.assert_called_once()
        self.assertEqual(result.content, "Actual transcript")
        source = Source.create_auto(URL, uuid4())
        source.mark_extracted(
            result.content,
            title=result.title,
            author=result.author,
            published_at=result.published_at,
            site_name=result.site_name,
            canonical_url=result.canonical_url,
            bib_metadata=result.bib_metadata,
        )
        section = APASection(
            APASectionType.BODY,
            DocumentNode(type=HEADING_1, children=(text_node("Body"),)),
            (
                DocumentNode(
                    type=PARAGRAPH,
                    children=(text_node(f"Claim [[cite:{source.id}]]"),),
                ),
            ),
        )
        reference = resolve_citations([section], [source], "es").references[0]
        self.assertIn("Science Channel", reference.to_apa_string())
        self.assertIn("2024, enero 2", reference.to_apa_string())
        self.assertIn("Actual title", reference.to_apa_string())

    async def test_persistence_roundtrip_and_retry_preserves_data(self):
        source = Source.create_auto(URL, uuid4())
        meta = BibMetadata(
            source_type="youtube",
            title="Title",
            author="Channel",
            published_year=2020,
            doi="10.1234/test",
            publisher="Publisher",
            duration_seconds=15,
            origins={
                "title": "yt_dlp",
                "author": "yt_dlp",
                "published_year": "yt_dlp",
                "doi": "crossref",
                "publisher": "crossref",
                "duration_seconds": "yt_dlp",
            },
        )
        source.mark_extracted(
            "Content", title=meta.title, author=meta.author, bib_metadata=meta
        )
        row = SupabaseSourceRepository._to_row(source)
        saved = SupabaseSourceRepository._to_entity(row)
        self.assertEqual(saved.bib_metadata.to_dict(), meta.to_dict())
        self.assertEqual(saved.published_year, 2020)
        saved.mark_extracted(
            "New content", bib_metadata=BibMetadata("youtube")
        )
        self.assertEqual(saved.bib_metadata.doi, "10.1234/test")
        self.assertEqual(saved.title, "Title")
        self.assertEqual(saved.published_year, 2020)

    async def test_http_cache_timeout_and_user_agent(self):
        client = MetadataHTTPClient("Scriva (mailto:contact@example.org)")
        response = httpx.Response(
            200, json={"title": "Verified"}, request=httpx.Request("GET", URL)
        )
        with patch(
            "infrastructure.metadata.http.httpx.AsyncClient"
        ) as factory:
            session = factory.return_value.__aenter__.return_value
            session.get = AsyncMock(return_value=response)
            first = await client.get_json(URL)
            first["title"] = "Modified"
            self.assertEqual((await client.get_json(URL))["title"], "Verified")
            session.get.assert_awaited_once()
            self.assertEqual(factory.call_args.kwargs["timeout"], 10)
            self.assertIn(
                "mailto:", factory.call_args.kwargs["headers"]["User-Agent"]
            )


class WebAndValidationTests(unittest.TestCase):
    def test_youtube_urls_and_host_validation(self):
        for url in [
            URL,
            "https://youtu.be/abcdefghijk?t=3",
            "https://youtube.com/shorts/abcdefghijk",
            "https://youtube.com/embed/abcdefghijk",
            "https://youtube.com/watch?list=123&v=abcdefghijk",
        ]:
            self.assertEqual(youtube_id(url), "abcdefghijk")
            self.assertEqual(detect_type(url), "youtube")
        self.assertIsNone(
            youtube_id("https://evil.test/youtube.com/abcdefghijk")
        )
        self.assertEqual(detect_type("https://site.test/article.pdf"), "web")

    def test_partial_and_invalid_dates_never_invent_day(self):
        for value, expected in [
            ("2023", 2023),
            ("2023-06", 2023),
            ("nonsense", None),
            ("2023-99", None),
        ]:
            meta = BibMetadata("web")
            set_date(meta, value, "html_meta")
            self.assertEqual(meta.published_year, expected)
            self.assertIsNone(meta.published_at)

    def test_json_ld_graph_and_meta_priority(self):
        meta = BibMetadata("web")
        read_web(
            meta,
            """<html><head><title>Generic site title</title>
          <meta name="author" content="HTML author">
          <script type="application/ld+json">{"@graph":[
            {"@type":"Organization","name":"Wrong title"},
            {"@type":"Article","headline":"Article title",
             "author":{"name":"JSON author"}, "datePublished":"2022",
             "publisher":{"name":"Publisher"}}]}</script>
          <link rel="canonical" href="/article"></head></html>""",
            "https://site.test/start",
        )
        self.assertEqual(meta.title, "Article title")
        self.assertEqual(meta.author, "HTML author")
        self.assertEqual(meta.published_year, 2022)
        self.assertEqual(meta.origins["title"], "json_ld")
        self.assertEqual(meta.url, "https://site.test/article")

    def test_academic_tags_and_multiple_authors(self):
        meta = BibMetadata("web")
        read_web(
            meta,
            """<html><head>
          <meta name="citation_title" content="Paper">
          <meta name="citation_author" content="First Author">
          <meta name="citation_author" content="Second Author">
          <meta name="DC.date" content="2024">
          <meta name="citation_doi" content="https://doi.org/10.1234/paper">
          </head></html>""",
            "https://site.test",
        )
        self.assertEqual(meta.author, "First Author; Second Author")
        self.assertEqual(meta.doi, "10.1234/paper")
        self.assertEqual(meta.published_year, 2024)

    @patch("htmldate.find_date", return_value="2020-02-03")
    def test_heuristic_date_marked_for_review(self, _find):
        meta = BibMetadata("web")
        read_web(
            meta, "<html><title>Title</title></html>", "https://site.test"
        )
        self.assertTrue(meta.needs_review)
        self.assertEqual(meta.origins["published_at"], "ninguno")


class AdditionalMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_plain_text_never_treated_as_file(self):
        meta = await MetadataEnricherAdapter().enrich("Text " * 10000, "text")
        self.assertIsNone(meta.title)
        self.assertTrue(meta.needs_review)

    async def test_txt_file_has_filename_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "Research notes.txt"
            path.write_text("Content")
            meta = await MetadataEnricherAdapter().enrich(str(path))
        self.assertEqual(meta.title, "Research notes")
        self.assertEqual(meta.origins["title"], "ninguno")

    async def test_web_crossref_enriches_academic_tags(self):
        http = MagicMock(spec=MetadataHTTPClient)
        http.get_json = AsyncMock(return_value=CROSSREF)
        meta = await MetadataEnricherAdapter(http=http).enrich(
            "https://site.test/paper",
            "web",
            html="""<html>
            <meta name="citation_doi" content="10.1234/test">
            <meta name="citation_title" content="Local paper">
            <meta name="DC.date" content="2020"></html>""",
        )
        self.assertEqual(meta.title, "Verified paper")
        self.assertEqual(meta.origins["title"], "crossref")
        self.assertEqual(meta.published_year, 2023)

    @patch(
        "infrastructure.metadata.youtube._extract_info",
        return_value={"title": ["Malformed"], "channel": 55},
    )
    async def test_malformed_primary_fields_allow_fallback(self, _info):
        http = MagicMock(spec=MetadataHTTPClient)
        http.get_json = AsyncMock(
            return_value={
                "title": "Valid title",
                "author_name": "Valid channel",
            }
        )
        meta = await MetadataEnricherAdapter(http=http).enrich(URL)
        self.assertEqual(meta.title, "Valid title")
        self.assertEqual(meta.author, "Valid channel")

    async def test_year_only_used_by_citation_service(self):
        source = Source.create_auto("Text", uuid4())
        source.mark_extracted(
            "Content",
            title="Work",
            author="Group Name",
            bib_metadata=BibMetadata("text", published_year=2023),
        )
        section = APASection(
            APASectionType.BODY,
            DocumentNode(type=HEADING_1, children=(text_node("Body"),)),
            (
                DocumentNode(
                    type=PARAGRAPH,
                    children=(text_node(f"Claim [[cite:{source.id}]]"),),
                ),
            ),
        )
        result = resolve_citations([section], [source], "es")
        self.assertIn(
            "Group Name. (2023). Work", result.references[0].to_apa_string()
        )
        self.assertIsNone(result.references[0].month)

    async def test_metadata_exposed_without_changing_source_content(self):
        from api.schemas.sources import SourceDetailResponseSchema
        from application.dtos.source_dtos import SourceDetailOutput

        source = Source.create_auto("Text", uuid4())
        source.created_at = datetime(2024, 1, 1)
        source.mark_extracted(
            "Original content",
            bib_metadata=BibMetadata("text", needs_review=True),
        )
        output = SourceDetailOutput.from_source(source)
        response = SourceDetailResponseSchema(
            id=output.id,
            type=output.source_type.value,
            raw=output.raw,
            content=output.content,
            created_at=output.created_at,
            char_count=output.char_count,
            bibliographic=output.bibliographic,
        )
        self.assertTrue(response.model_dump()["bibliographic"]["needs_review"])
        self.assertEqual(response.content, "Original content")

    async def test_uploaded_names_preserved_without_path_traversal(self):
        from io import BytesIO

        from api.v1.documents import _copy_uploads
        from starlette.datastructures import UploadFile

        with tempfile.TemporaryDirectory() as folder:
            uploads = [
                UploadFile(BytesIO(b"one"), filename="../notes.txt"),
                UploadFile(BytesIO(b"two"), filename="notes.txt"),
            ]
            paths = await _copy_uploads(uploads, Path(folder))
            self.assertNotEqual(paths[0], paths[1])
            for path in paths:
                self.assertEqual(Path(path).name, "notes.txt")
                self.assertTrue(Path(path).is_relative_to(folder))
            self.assertEqual(Path(paths[0]).read_bytes(), b"one")
            self.assertEqual(Path(paths[1]).read_bytes(), b"two")


if __name__ == "__main__":
    unittest.main()
