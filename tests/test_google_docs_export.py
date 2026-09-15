from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

from domain.value_objects.apa_structure import APASectionType
from domain.value_objects.document_node import (
    BOOKMARK,
    BULLETED_LIST,
    HEADING_2,
    LIST_ITEM,
    MARK_COLOR,
    MARK_HIGHLIGHT,
    PARAGRAPH,
    TABLE,
    TABLE_CELL,
    TABLE_OF_CONTENTS,
    TABLE_ROW,
    DocumentNode,
    Mark,
    hyperlink_node,
    text_node,
)
from infrastructure.export.document_exporter_resolver_adapter import (
    DocumentExporterResolverAdapter,
)
from infrastructure.export.google_docs_exporter_adapter import (
    GoogleDocsExporterAdapter,
)

from tests.test_export_table_of_contents import _document_fixture


class GoogleDocsExporterResolverTest(unittest.TestCase):
    def test_resolves_fresh_credentials_for_every_google_docs_export(
        self,
    ) -> None:
        user_id = uuid4()
        credentials_repository = AsyncMock()
        credentials_repository.get_refresh_token.side_effect = [
            "refresh-token-1",
            "refresh-token-2",
        ]
        token_provider = AsyncMock()
        token_provider.get_access_token.side_effect = [
            "access-token-1",
            "access-token-2",
        ]
        resolver = DocumentExporterResolverAdapter(
            pdf_exporter=object(),
            google_credentials_repository=credentials_repository,
            google_token_provider=token_provider,
        )

        first = asyncio.run(resolver.resolve("google_docs", user_id))
        second = asyncio.run(resolver.resolve("google_docs", user_id))

        self.assertIsNot(first, second)
        self.assertEqual(first._credentials.token, "access-token-1")
        self.assertEqual(second._credentials.token, "access-token-2")
        self.assertEqual(
            credentials_repository.get_refresh_token.await_args_list,
            [unittest.mock.call(user_id), unittest.mock.call(user_id)],
        )
        self.assertEqual(
            token_provider.get_access_token.await_args_list,
            [
                unittest.mock.call("refresh-token-1"),
                unittest.mock.call("refresh-token-2"),
            ],
        )

    def test_keeps_legacy_google_doc_export_target(self) -> None:
        credentials_repository = AsyncMock()
        credentials_repository.get_refresh_token.return_value = "refresh"
        token_provider = AsyncMock()
        token_provider.get_access_token.return_value = "access"
        resolver = DocumentExporterResolverAdapter(
            pdf_exporter=object(),
            google_credentials_repository=credentials_repository,
            google_token_provider=token_provider,
        )

        exporter = asyncio.run(resolver.resolve("google_doc", uuid4()))

        self.assertEqual(exporter._credentials.token, "access")


class GoogleDocsNodeTreeExporterTest(unittest.TestCase):
    def test_builds_content_and_formatting_from_document_nodes(self) -> None:
        document = _document_fixture()
        body = document.get_section(APASectionType.BODY)
        assert body is not None
        rich_paragraph = DocumentNode(
            type=PARAGRAPH,
            styles={"textAlign": "right"},
            children=(
                text_node(
                    "Styled ",
                    marks=(Mark("bold"), Mark(MARK_COLOR, "#FF0000")),
                ),
                hyperlink_node(
                    (text_node("link"),), "https://example.com/source"
                ),
            ),
        )
        bullet_list = DocumentNode(
            type=BULLETED_LIST,
            children=(
                DocumentNode(
                    type=LIST_ITEM,
                    children=(text_node("First item"),),
                ),
                DocumentNode(
                    type=LIST_ITEM,
                    children=(text_node("Second item"),),
                ),
            ),
        )
        table = DocumentNode(
            type=TABLE,
            children=(
                DocumentNode(
                    type=TABLE_ROW,
                    children=(
                        DocumentNode(
                            type=TABLE_CELL,
                            children=(
                                DocumentNode(
                                    type=PARAGRAPH,
                                    children=(text_node("Cell A"),),
                                ),
                            ),
                        ),
                        DocumentNode(
                            type=TABLE_CELL,
                            children=(
                                DocumentNode(
                                    type=PARAGRAPH,
                                    children=(text_node("Cell B"),),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        document.sections = [
            replace(
                section,
                body_nodes=(
                    DocumentNode(
                        type=HEADING_2,
                        children=(text_node("Node heading"),),
                    ),
                    rich_paragraph,
                    bullet_list,
                    table,
                ),
            )
            if section.section_type is APASectionType.BODY
            else section
            for section in document.sections
        ]

        requests = GoogleDocsExporterAdapter("access")._build_requests(
            document
        )

        inserted_text = [
            request["insertText"]["text"]
            for request in requests
            if "insertText" in request
        ]
        self.assertIn("Node heading\n", inserted_text)
        self.assertIn("Styled link\n", inserted_text)
        self.assertIn("First item\n", inserted_text)
        self.assertIn("Second item\n", inserted_text)
        self.assertTrue(any("insertTable" in item for item in requests))
        self.assertTrue(any("insertPageBreak" in item for item in requests))
        self.assertEqual(
            sum("createParagraphBullets" in item for item in requests), 2
        )

        paragraph_styles = [
            item["updateParagraphStyle"]["paragraphStyle"]
            for item in requests
            if "updateParagraphStyle" in item
        ]
        self.assertTrue(
            any(
                style.get("namedStyleType") == "HEADING_2"
                for style in paragraph_styles
            )
        )
        self.assertTrue(
            any(style.get("alignment") == "END" for style in paragraph_styles)
        )
        text_styles = [
            item["updateTextStyle"]["textStyle"]
            for item in requests
            if "updateTextStyle" in item
        ]
        self.assertTrue(any(style.get("bold") for style in text_styles))
        self.assertTrue(
            any(
                style.get("link", {}).get("url")
                == "https://example.com/source"
                for style in text_styles
            )
        )

    def test_preserves_highlights_bookmarks_and_meta_only_headings(
        self,
    ) -> None:
        document = _document_fixture()
        body = document.get_section(APASectionType.BODY)
        assert body is not None
        document.sections = [
            replace(
                section,
                body_nodes=(
                    DocumentNode(
                        type=HEADING_2,
                        metadata={"meta_only": True},
                        children=(text_node("Internal title"),),
                    ),
                    DocumentNode(
                        type=PARAGRAPH,
                        children=(
                            text_node(
                                "Named",
                                marks=(Mark(MARK_HIGHLIGHT, "yellow"),),
                            ),
                            text_node(
                                " RGB",
                                marks=(Mark(MARK_HIGHLIGHT, "rgb(1, 2, 3)"),),
                            ),
                            DocumentNode(
                                type=BOOKMARK,
                                id="bookmark-1",
                                children=(text_node(" target"),),
                            ),
                        ),
                    ),
                ),
            )
            if section.section_type is APASectionType.BODY
            else section
            for section in document.sections
        ]

        requests = GoogleDocsExporterAdapter("access")._build_requests(
            document
        )

        inserted = [
            item["insertText"]["text"]
            for item in requests
            if "insertText" in item
        ]
        self.assertNotIn("Internal title\n", inserted)
        highlight_styles = [
            item["updateTextStyle"]["textStyle"]
            for item in requests
            if "updateTextStyle" in item
            and "backgroundColor" in item["updateTextStyle"]["textStyle"]
        ]
        self.assertEqual(len(highlight_styles), 2)
        self.assertTrue(
            any(
                item.get("createNamedRange", {}).get("name") == "bookmark-1"
                for item in requests
            )
        )

    def test_keeps_toc_placeholder_for_the_second_pass(self) -> None:
        document = _document_fixture()
        body = document.get_section(APASectionType.BODY)
        assert body is not None
        document.sections = [
            replace(
                section,
                body_nodes=(DocumentNode(type=TABLE_OF_CONTENTS),),
            )
            if section.section_type is APASectionType.BODY
            else section
            for section in document.sections
        ]

        requests = GoogleDocsExporterAdapter("access")._build_requests(
            document
        )

        self.assertTrue(
            any(
                "SCRIVA_TOC" in item.get("insertText", {}).get("text", "")
                for item in requests
            )
        )
