from __future__ import annotations

from dataclasses import replace

from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    HYPERLINK,
    LIST_TYPES,
    MARK_LINK,
    PAGE_BREAK,
    TABLE_OF_CONTENTS,
    DocumentNode,
    Mark,
)


def merge_docx_edits(
    original: list[APASection], parsed: list[APASection]
) -> list[APASection]:
    """Retain canonical structure when an editor only changed inline marks.

    Browser DOCX editors commonly flatten fields, lists, and page-break
    paragraphs. If a section's text stream is unchanged, its original node
    topology is authoritative while marks from the uploaded DOCX are applied
    by character position. Sections with actual text edits use the parsed
    representation.
    """
    original_by_type = {section.section_type: section for section in original}
    merged: list[APASection] = []
    for incoming in parsed:
        current = original_by_type.get(incoming.section_type)
        if current is None:
            merged.append(incoming)
            continue
        if incoming.section_type is APASectionType.INDEX:
            merged.append(_merge_index(current, incoming))
            continue
        incoming_spans, incoming_text = _mark_spans(incoming.nodes)
        _, current_text = _mark_spans(current.nodes)
        if incoming_text != current_text:
            merged.append(incoming)
            continue
        style_spans = _style_spans(incoming.nodes)
        list_spans = _list_spans(incoming.nodes)
        offset = 0
        heading_nodes, offset = _merge_nodes(
            (current.heading,),
            incoming_spans,
            style_spans,
            list_spans,
            offset,
        )
        body_nodes, _ = _merge_nodes(
            current.body_nodes,
            incoming_spans,
            style_spans,
            list_spans,
            offset,
        )
        body_nodes = _merge_page_breaks(body_nodes, incoming.body_nodes)
        merged.append(
            APASection(
                section_type=current.section_type,
                heading=heading_nodes[0],
                body_nodes=body_nodes,
            )
        )
    return merged


def _merge_page_breaks(
    canonical: tuple[DocumentNode, ...],
    incoming: tuple[DocumentNode, ...],
) -> tuple[DocumentNode, ...]:
    """Apply the edited DOCX's top-level page-break positions and counts.

    Page breaks contain no text, so the text-based topology merge cannot
    detect additions or removals. DOCX parsers represent them as top-level
    nodes between paragraphs, which lets us restore them by character offset
    without sacrificing canonical list/table structure.
    """
    breaks_by_offset: dict[int, list[DocumentNode]] = {}
    offset = 0
    for node in incoming:
        if node.type == PAGE_BREAK:
            breaks_by_offset.setdefault(offset, []).append(node)
        else:
            offset += len(node.plain_text())

    result: list[DocumentNode] = []
    offset = 0
    result.extend(breaks_by_offset.pop(offset, ()))
    for node in canonical:
        if node.type == PAGE_BREAK:
            continue
        result.append(node)
        offset += len(node.plain_text())
        result.extend(breaks_by_offset.pop(offset, ()))

    # A malformed/unusual editor structure should not silently lose breaks.
    for remaining in breaks_by_offset.values():
        result.extend(remaining)
    return tuple(result)


def _merge_index(current: APASection, incoming: APASection) -> APASection:
    incoming_toc = next(
        (
            node
            for node in incoming.body_nodes
            if node.type == TABLE_OF_CONTENTS
        ),
        None,
    )
    fallback_styles = next(
        (node.styles for node in incoming.body_nodes if node.styles), {}
    )
    toc_styles = (
        incoming_toc.styles if incoming_toc is not None else fallback_styles
    )
    body = tuple(
        replace(node, styles=toc_styles)
        if node.type == TABLE_OF_CONTENTS
        else node
        for node in current.body_nodes
    )
    return APASection(
        section_type=APASectionType.INDEX,
        heading=incoming.heading,
        body_nodes=body,
    )


def _mark_spans(
    nodes: tuple[DocumentNode, ...],
) -> tuple[list[tuple[int, int, tuple[Mark, ...]]], str]:
    spans: list[tuple[int, int, tuple[Mark, ...]]] = []
    pieces: list[str] = []
    offset = 0
    for node in nodes:
        for leaf, inherited_marks in _leaves_with_context(node):
            assert leaf.text is not None
            end = offset + len(leaf.text)
            spans.append((offset, end, (*leaf.marks, *inherited_marks)))
            pieces.append(leaf.text)
            offset = end
    return spans, "".join(pieces)


def _leaves(node: DocumentNode):
    if node.text is not None:
        yield node
        return
    for child in node.children:
        yield from _leaves(child)


def _leaves_with_context(
    node: DocumentNode,
    inherited_marks: tuple[Mark, ...] = (),
):
    if node.text is not None:
        yield node, inherited_marks
        return
    marks = inherited_marks
    if node.type == HYPERLINK and node.metadata.get("url"):
        marks = (
            *marks,
            Mark(
                MARK_LINK,
                {
                    key: value
                    for key, value in node.metadata.items()
                    if key in {"url", "tooltip"}
                },
            ),
        )
    for child in node.children:
        yield from _leaves_with_context(child, marks)


def _style_spans(
    nodes: tuple[DocumentNode, ...],
) -> dict[tuple[int, int, str | None], dict]:
    spans: dict[tuple[int, int, str | None], dict] = {}
    offset = 0
    for node in nodes:
        offset = _collect_style_spans(node, offset, spans)
    return spans


def _collect_style_spans(
    node: DocumentNode,
    offset: int,
    spans: dict[tuple[int, int, str | None], dict],
) -> int:
    if node.text is not None:
        return offset + len(node.text)
    start = offset
    for child in node.children:
        offset = _collect_style_spans(child, offset, spans)
    if node.styles and offset > start:
        spans[(start, offset, node.type)] = node.styles
    return offset


def _list_spans(
    nodes: tuple[DocumentNode, ...],
) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    offset = 0
    for node in nodes:
        offset = _collect_list_spans(node, offset, spans)
    return spans


def _collect_list_spans(
    node: DocumentNode,
    offset: int,
    spans: list[tuple[int, int, str]],
) -> int:
    if node.text is not None:
        return offset + len(node.text)
    start = offset
    for child in node.children:
        offset = _collect_list_spans(child, offset, spans)
    if node.type in LIST_TYPES and offset > start:
        spans.append((start, offset, node.type))
    return offset


def _merge_nodes(
    nodes: tuple[DocumentNode, ...],
    spans: list[tuple[int, int, tuple[Mark, ...]]],
    style_spans: dict[tuple[int, int, str | None], dict],
    list_spans: list[tuple[int, int, str]],
    offset: int,
) -> tuple[tuple[DocumentNode, ...], int]:
    merged: list[DocumentNode] = []
    for node in nodes:
        replacements, offset = _merge_node(
            node, spans, style_spans, list_spans, offset
        )
        merged.extend(replacements)
    return tuple(merged), offset


def _merge_node(
    node: DocumentNode,
    spans: list[tuple[int, int, tuple[Mark, ...]]],
    style_spans: dict[tuple[int, int, str | None], dict],
    list_spans: list[tuple[int, int, str]],
    offset: int,
) -> tuple[tuple[DocumentNode, ...], int]:
    if node.text is None:
        start = offset
        children, offset = _merge_nodes(
            node.children, spans, style_spans, list_spans, offset
        )
        incoming_styles = style_spans.get((start, offset, node.type), {})
        styles = {**node.styles, **incoming_styles}
        node_type = node.type
        if node_type in LIST_TYPES:
            incoming_types = {
                incoming_type
                for span_start, span_end, incoming_type in list_spans
                if span_start >= start and span_end <= offset
            }
            if len(incoming_types) == 1:
                node_type = incoming_types.pop()
        return (
            replace(
                node,
                type=node_type,
                children=children,
                styles=styles,
            ),
        ), offset
    if not node.text:
        return (node,), offset

    end = offset + len(node.text)
    pieces: list[DocumentNode] = []
    cursor = offset
    for span_start, span_end, marks in spans:
        overlap_start = max(cursor, span_start)
        overlap_end = min(end, span_end)
        if overlap_start >= overlap_end:
            continue
        relative_start = overlap_start - offset
        relative_end = overlap_end - offset
        pieces.append(
            replace(
                node,
                text=node.text[relative_start:relative_end],
                marks=marks,
            )
        )
        cursor = overlap_end
        if cursor == end:
            break
    return tuple(pieces) or (node,), end
