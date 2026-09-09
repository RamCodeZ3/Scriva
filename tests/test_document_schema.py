from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from tests.test_export_table_of_contents import _document_fixture


class DocumentSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).parents[1] / "document.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema)

    def test_generated_tree_matches_v2_schema(self) -> None:
        errors = sorted(
            self.validator.iter_errors(_document_fixture().to_node_tree()),
            key=lambda error: list(error.absolute_path),
        )

        self.assertEqual(
            errors,
            [],
            "\n".join(error.message for error in errors),
        )

    def test_accepts_breaks_with_id_without_section_type(self) -> None:
        for node_type in ("page-break", "section-break"):
            tree = _minimal_tree([{"id": f"{node_type}-1", "type": node_type}])

            self.assertEqual(list(self.validator.iter_errors(tree)), [])

    def test_requires_id_for_breaks(self) -> None:
        tree = _minimal_tree([{"type": "page-break"}])

        self.assertTrue(list(self.validator.iter_errors(tree)))

    def test_requires_id_and_section_type_for_semantic_root_nodes(
        self,
    ) -> None:
        tree = _minimal_tree(
            [
                {
                    "type": "heading-1",
                    "children": [{"text": "Índice"}],
                }
            ]
        )

        self.assertTrue(list(self.validator.iter_errors(tree)))

    def test_accepts_table_of_contents_with_root_identity(self) -> None:
        tree = _minimal_tree(
            [
                {
                    "id": "toc-1",
                    "type": "table-of-contents",
                    "section_type": "index",
                }
            ]
        )

        self.assertEqual(list(self.validator.iter_errors(tree)), [])

    def test_rejects_string_page_margin(self) -> None:
        tree = _minimal_tree([])
        tree["global_style"]["pageMargin"] = "1in"

        self.assertTrue(list(self.validator.iter_errors(tree)))

    def test_rejects_deprecated_margin_top(self) -> None:
        tree = _minimal_tree(
            [
                {
                    "id": "paragraph-1",
                    "type": "paragraph",
                    "section_type": "body",
                    "style": {"marginTop": "7.5pt"},
                    "children": [{"text": "Invalid"}],
                }
            ]
        )

        self.assertTrue(list(self.validator.iter_errors(tree)))

    def test_rejects_nested_hyperlinks(self) -> None:
        nested = {
            "id": "link-2",
            "type": "hyperlink",
            "metadata": {"url": "https://example.com"},
            "children": [{"text": "activity"}],
        }
        tree = _minimal_tree(
            [
                {
                    "id": "paragraph-1",
                    "type": "paragraph",
                    "section_type": "body",
                    "children": [
                        {
                            "id": "link-1",
                            "type": "hyperlink",
                            "metadata": {"url": "https://example.com"},
                            "children": [nested],
                        }
                    ],
                }
            ]
        )

        self.assertTrue(list(self.validator.iter_errors(tree)))


def _minimal_tree(children: list[dict]) -> dict:
    return {
        "type": "document",
        "meta": {"title": "Test", "style_guide": "APA7", "version": "2.0"},
        "global_style": {
            "pageMargin": {
                "top": "1in",
                "right": "1in",
                "bottom": "1in",
                "left": "1in",
            }
        },
        "children": children,
    }


if __name__ == "__main__":
    unittest.main()
