from __future__ import annotations

import unittest

from application.services.document_edit_merge import merge_docx_edits
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    BULLETED_LIST,
    HEADING_1,
    LIST_ITEM,
    MARK_COLOR,
    NUMBERED_LIST,
    PAGE_BREAK,
    PARAGRAPH,
    TABLE_OF_CONTENTS,
    DocumentNode,
    Mark,
    hyperlink_node,
    page_break_node,
    text_node,
)


class MergeDocxEditsTest(unittest.TestCase):
    def test_preserves_topology_and_applies_inline_marks(self) -> None:
        original = _section(
            (
                DocumentNode(
                    type=BULLETED_LIST,
                    children=(
                        _list_item("Alpha"),
                        _list_item("Beta"),
                    ),
                ),
                _paragraph("Gamma"),
                page_break_node(),
            )
        )
        parsed = _section(
            (
                _paragraph("Alpha"),
                _paragraph("Beta", marks=(Mark(MARK_COLOR, "#FF0000"),)),
                _paragraph("Gamma", styles={"textAlign": "right"}),
                page_break_node(),
            )
        )

        merged = merge_docx_edits([original], [parsed])[0]

        self.assertEqual(merged.body_nodes[0].type, BULLETED_LIST)
        self.assertEqual(merged.body_nodes[2].type, PAGE_BREAK)
        self.assertEqual(merged.body_nodes[1].styles["textAlign"], "right")
        second_item = merged.body_nodes[0].children[1]
        self.assertIn(
            Mark(MARK_COLOR, "#FF0000"), second_item.children[0].marks
        )

    def test_preserves_multiple_page_breaks_added_by_editor(self) -> None:
        original = _section((_paragraph("Content"), page_break_node()))
        parsed = _section(
            (
                _paragraph("Content"),
                page_break_node(),
                page_break_node(),
            )
        )

        merged = merge_docx_edits([original], [parsed])[0]

        self.assertEqual(
            [node.type for node in merged.body_nodes],
            [PARAGRAPH, PAGE_BREAK, PAGE_BREAK],
        )

    def test_applies_list_type_change_without_losing_items(self) -> None:
        original = _section(
            (
                DocumentNode(
                    type=BULLETED_LIST,
                    children=(_list_item("Alpha"), _list_item("Beta")),
                ),
            )
        )
        parsed = _section(
            (
                DocumentNode(
                    type=NUMBERED_LIST,
                    children=(_list_item("Alpha"),),
                ),
                DocumentNode(
                    type=NUMBERED_LIST,
                    children=(_list_item("Beta"),),
                ),
            )
        )

        merged = merge_docx_edits([original], [parsed])[0]

        self.assertEqual(merged.body_nodes[0].type, NUMBERED_LIST)
        self.assertEqual(len(merged.body_nodes[0].children), 2)

    def test_uses_parsed_structure_when_text_changed(self) -> None:
        original = _section((_paragraph("Original"), page_break_node()))
        parsed = _section((_paragraph("Edited"),))

        merged = merge_docx_edits([original], [parsed])[0]

        self.assertEqual(merged.body_nodes, parsed.body_nodes)

    def test_preserves_hyperlink_from_uploaded_docx_when_text_is_unchanged(
        self,
    ) -> None:
        original = _section((_paragraph("Scriva"),))
        parsed = _section(
            (
                DocumentNode(
                    type=PARAGRAPH,
                    children=(
                        hyperlink_node(
                            (text_node("Scriva"),),
                            "https://example.com/edited",
                        ),
                    ),
                ),
            )
        )

        merged = merge_docx_edits([original], [parsed])[0]
        serialized = merged.body_nodes[0].to_dict()

        self.assertEqual(serialized["children"][0]["type"], "hyperlink")
        self.assertEqual(
            serialized["children"][0]["metadata"]["url"],
            "https://example.com/edited",
        )

    def test_preserves_toc_structure_and_applies_index_styles(self) -> None:
        original = APASection(
            APASectionType.INDEX,
            DocumentNode(type=HEADING_1, children=(text_node("Index"),)),
            (DocumentNode(type=TABLE_OF_CONTENTS), page_break_node()),
        )
        incoming = APASection(
            APASectionType.INDEX,
            DocumentNode(
                type=HEADING_1,
                children=(text_node("Styled index"),),
                styles={"textAlign": "center"},
            ),
            (_paragraph("Flattened entry", styles={"marginLeft": "24pt"}),),
        )

        merged = merge_docx_edits([original], [incoming])[0]

        self.assertEqual(merged.title, "Styled index")
        self.assertEqual(merged.heading.styles["textAlign"], "center")
        self.assertEqual(merged.body_nodes[0].type, TABLE_OF_CONTENTS)
        self.assertEqual(merged.body_nodes[0].styles["marginLeft"], "24pt")


def _section(body: tuple[DocumentNode, ...]) -> APASection:
    return APASection(
        APASectionType.BODY,
        DocumentNode(type=HEADING_1, children=(text_node("Development"),)),
        body,
    )


def _paragraph(
    text: str,
    *,
    marks: tuple[Mark, ...] = (),
    styles: dict | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=PARAGRAPH,
        children=(text_node(text, marks=marks),),
        styles=styles or {},
    )


def _list_item(text: str) -> DocumentNode:
    return DocumentNode(type=LIST_ITEM, children=(text_node(text),))


if __name__ == "__main__":
    unittest.main()
