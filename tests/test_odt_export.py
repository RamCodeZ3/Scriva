from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

from domain.value_objects.apa_structure import APASectionType
from domain.value_objects.document_node import (
    MARK_BACKGROUND_SHADING,
    MARK_HIGHLIGHT,
    MARK_LINK,
    PARAGRAPH,
    TABLE,
    TABLE_CELL,
    TABLE_ROW,
    DocumentNode,
    Mark,
    text_node,
)
from infrastructure.export.document_exporter_resolver_adapter import (
    DocumentExporterResolverAdapter,
)
from infrastructure.export.odt_document_exporter_adapter import (
    OdtDocumentExporterAdapter,
)

from tests.test_export_table_of_contents import _document_fixture


class OdtDocumentExporterTest(unittest.TestCase):
    def test_resolver_accepts_odt_target(self) -> None:
        odt_exporter = OdtDocumentExporterAdapter()
        resolver = DocumentExporterResolverAdapter(
            pdf_exporter=object(),
            google_credentials_repository=AsyncMock(),
            google_token_provider=AsyncMock(),
            odt_exporter=odt_exporter,
        )

        resolved = asyncio.run(resolver.resolve("odt", uuid4()))

        self.assertIs(resolved, odt_exporter)

    def test_exports_valid_odt_with_toc_bookmarks_and_page_numbers(
        self,
    ) -> None:
        result = asyncio.run(
            OdtDocumentExporterAdapter().export(_document_fixture())
        )

        self.assertEqual(result.file_name, "TOC test.odt")
        self.assertEqual(
            result.content_type,
            "application/vnd.oasis.opendocument.text",
        )
        assert result.file_bytes is not None
        with ZipFile(BytesIO(result.file_bytes)) as archive:
            self.assertEqual(
                archive.read("mimetype"),
                b"application/vnd.oasis.opendocument.text",
            )
            content = archive.read("content.xml").decode("utf-8")
            styles = archive.read("styles.xml").decode("utf-8")

        self.assertIn('text:name="toc-heading-1"', content)
        self.assertIn('xlink:href="#toc-heading-1"', content)
        self.assertIn("Introducción", content)
        self.assertIn("Tema principal", content)
        self.assertRegex(content, r"Tema principal</text:a>.*?[1-9]")
        self.assertIn('style:type="right"', content)
        self.assertIn('style:leader-style="dotted"', content)
        self.assertIn("text:page-number", styles)
        self.assertIn('style:master-page-name="Scriva"', styles)

    def test_declares_table_grid_and_preserves_columns(self) -> None:
        document = _document_fixture()
        table_node = DocumentNode(
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
                                    children=(text_node("First heading"),),
                                ),
                            ),
                        ),
                        DocumentNode(
                            type=TABLE_CELL,
                            children=(
                                DocumentNode(
                                    type=PARAGRAPH,
                                    children=(text_node("Second heading"),),
                                ),
                            ),
                        ),
                    ),
                ),
                DocumentNode(
                    type=TABLE_ROW,
                    children=(
                        DocumentNode(
                            type=TABLE_CELL,
                            children=(
                                DocumentNode(
                                    type=PARAGRAPH,
                                    children=(text_node("Left"),),
                                ),
                            ),
                        ),
                        DocumentNode(
                            type=TABLE_CELL,
                            children=(
                                DocumentNode(
                                    type=PARAGRAPH,
                                    children=(text_node("Right"),),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        document.sections = [
            replace(section, body_nodes=(table_node,))
            if section.section_type is APASectionType.INTRODUCTION
            else section
            for section in document.sections
        ]

        content = OdtDocumentExporterAdapter()._build_sync(document)
        with ZipFile(BytesIO(content)) as archive:
            xml = archive.read("content.xml").decode("utf-8")

        self.assertIn('table:number-columns-repeated="2"', xml)
        self.assertIn("First heading", xml)
        self.assertIn("Second heading", xml)
        self.assertIn("Left", xml)
        self.assertIn("Right", xml)

    def test_preserves_inline_marks_and_links(self) -> None:
        document = _document_fixture()
        introduction = document.get_section(APASectionType.INTRODUCTION)
        assert introduction is not None
        marked = DocumentNode(
            type=PARAGRAPH,
            children=(
                text_node(
                    "Highlighted",
                    marks=(
                        Mark(MARK_HIGHLIGHT, "yellow"),
                        Mark("underline"),
                    ),
                ),
                text_node(
                    " shaded",
                    marks=(
                        Mark(MARK_BACKGROUND_SHADING, "#ABCDEF"),
                        Mark("strikethrough"),
                    ),
                ),
                text_node(
                    " source",
                    marks=(Mark(MARK_LINK, {"url": "https://example.com"}),),
                ),
            ),
        )
        document.sections = [
            replace(section, body_nodes=(marked,))
            if section.section_type is APASectionType.INTRODUCTION
            else section
            for section in document.sections
        ]

        content = OdtDocumentExporterAdapter()._build_sync(document)
        with ZipFile(BytesIO(content)) as archive:
            xml = archive.read("content.xml").decode("utf-8")

        self.assertIn('fo:background-color="#FFFF00"', xml)
        self.assertIn('fo:background-color="#ABCDEF"', xml)
        self.assertIn('style:text-underline-style="solid"', xml)
        self.assertIn('style:text-line-through-style="solid"', xml)
        self.assertIn('xlink:href="https://example.com"', xml)


if __name__ == "__main__":
    unittest.main()
