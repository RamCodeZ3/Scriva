from __future__ import annotations

import unittest

from domain.exceptions import DocumentBuildError
from domain.value_objects.document_node import (
    HYPERLINK,
    MARK_HIGHLIGHT,
    MARK_LINK,
    PARAGRAPH,
    DocumentNode,
    Mark,
    hyperlink_node,
)


class DocumentNodeV2Test(unittest.TestCase):
    def test_serializes_text_format_as_style(self) -> None:
        node = DocumentNode(
            text="Formatted",
            marks=(Mark("bold"), Mark("fontSize", "12pt")),
        )

        self.assertEqual(
            node.to_dict(),
            {
                "text": "Formatted",
                "style": {"bold": True, "fontSize": "12pt"},
            },
        )

    def test_reads_legacy_marks_and_styles(self) -> None:
        node = DocumentNode.from_dict(
            {
                "type": PARAGRAPH,
                "styles": {"textAlign": "right"},
                "children": [{"text": "Legacy", "marks": [{"type": "bold"}]}],
            }
        )

        self.assertEqual(node.styles, {"textAlign": "right"})
        self.assertEqual(node.children[0].marks, (Mark("bold"),))

    def test_migrates_legacy_link_to_hyperlink_node(self) -> None:
        node = DocumentNode(
            type=PARAGRAPH,
            children=(
                DocumentNode(
                    text="Scriva",
                    marks=(
                        Mark(MARK_LINK, {"url": "https://example.com"}),
                        Mark("bold"),
                    ),
                ),
            ),
        )

        serialized = node.to_dict()
        hyperlink = serialized["children"][0]

        self.assertEqual(hyperlink["type"], HYPERLINK)
        self.assertEqual(hyperlink["metadata"]["url"], "https://example.com")
        self.assertEqual(
            hyperlink["children"],
            [{"text": "Scriva", "style": {"bold": True}}],
        )

    def test_migrates_free_hex_highlight_to_background_shading(self) -> None:
        node = DocumentNode(
            text="Shaded",
            marks=(Mark(MARK_HIGHLIGHT, "#E8E8E8"),),
        )

        self.assertEqual(
            node.to_dict()["style"],
            {"backgroundShading": "#E8E8E8"},
        )

    def test_rejects_nested_hyperlink(self) -> None:
        inner = hyperlink_node(
            (DocumentNode(text="nested"),), "https://example.com"
        )

        with self.assertRaises(DocumentBuildError):
            hyperlink_node((inner,), "https://example.com")

    def test_normalizes_deprecated_imported_styles(self) -> None:
        node = DocumentNode.from_dict(
            {
                "type": PARAGRAPH,
                "styles": {
                    "marginTop": "7.5pt",
                    "columnWidths": ["100pt"],
                },
                "children": [{"text": "Imported"}],
            }
        )

        self.assertEqual(node.styles, {"spaceBefore": "7.5pt"})

    def test_rejects_deprecated_styles_in_new_nodes(self) -> None:
        with self.assertRaisesRegex(DocumentBuildError, "marginTop"):
            DocumentNode(
                type=PARAGRAPH,
                styles={"marginTop": "7.5pt"},
                children=(DocumentNode(text="Invalid"),),
            )

    def test_flattens_persisted_duplicate_hyperlink(self) -> None:
        node = DocumentNode.from_dict(
            {
                "id": "node-202",
                "type": HYPERLINK,
                "metadata": {"url": "https://example.com"},
                "children": [
                    {
                        "id": "node-8",
                        "type": HYPERLINK,
                        "metadata": {"url": "https://example.com"},
                        "children": [{"text": "activity"}],
                    }
                ],
            }
        )

        self.assertEqual(node.id, "node-202")
        self.assertEqual(node.children[0].text, "activity")
        self.assertEqual(len(node.children), 1)


if __name__ == "__main__":
    unittest.main()
